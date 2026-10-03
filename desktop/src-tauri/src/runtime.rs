//! The native host only supervises Python and routes commands/events.
//! User code and DataFrames never execute in a WebView or the Rust event loop.

use serde_json::{json, Value};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::Emitter;
use tokio::sync::oneshot;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(120);
// Match the Python supervisor limit and reject before writing to its pipe.
const MAX_REQUEST_BYTES: usize = 24 * 1024 * 1024;
type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>>;

#[derive(Default)]
pub struct Backend {
    client: Mutex<Option<Arc<RuntimeClient>>>,
}

impl Backend {
    pub async fn request(
        &self,
        app: tauri::AppHandle,
        method: String,
        params: Value,
    ) -> Result<Value, String> {
        if !allowed_method(&method) {
            return Err(format!("Unsupported runtime method: {method}"));
        }
        if !params.is_object() {
            return Err("Runtime parameters must be an object".into());
        }
        let client = {
            let mut current = self
                .client
                .lock()
                .map_err(|_| "Runtime state unavailable")?;
            if current
                .as_ref()
                .is_some_and(|client| client.closed.load(Ordering::Acquire))
            {
                current.take();
            }
            if current.is_none() {
                *current = Some(Arc::new(RuntimeClient::start(app)?));
            }
            Arc::clone(current.as_ref().ok_or("Runtime failed to start")?)
        };
        client.request(method, params).await
    }

    pub fn shutdown(&self) {
        if let Ok(mut current) = self.client.lock() {
            if let Some(client) = current.take() {
                client.stop();
            }
        }
    }
}

fn allowed_method(method: &str) -> bool {
    matches!(
        method,
        "system.info"
            | "system.activity"
            | "system.flush_workspace"
            | "session.create"
            | "session.close"
            | "connection.connect"
            | "schema.get"
            | "execution.run"
            | "execution.cancel"
            | "result.page"
            | "result.release"
            | "workspace.read"
            | "workspace.write"
            | "connections.list"
            | "connections.save"
            | "connections.delete"
            | "connections.clone"
            | "connections.move"
            | "connections.reorder"
            | "connections.import"
            | "connections.export"
            | "groups.save"
            | "groups.delete"
            | "connection.disconnect"
            | "explorer.list"
            | "explorer.details"
            | "explorer.query"
            | "explorer.use_database"
            | "language.complete"
            | "language.format"
            | "language.diagnostics"
            | "parameters.scan"
            | "connection.test"
            | "connection.test_cancel"
            | "connection.idle_timeout"
            | "data.import"
            | "variable.inspect"
            | "variable.delete"
            | "result.export"
            | "result.summary"
            | "result.chart"
            | "result.chart_export"
            | "result.artifact_write"
            | "result.export_table"
            | "document.read"
            | "document.script_export"
            | "packages.list"
            | "packages.search"
            | "packages.install"
            | "packages.update"
            | "packages.uninstall"
            | "packages.sources"
            | "pynia.catalog"
            | "pynia.state"
            | "pynia.select_agent"
            | "pynia.prompt"
            | "pynia.cancel"
            | "pynia.clear"
            | "pynia.config"
            | "pynia.answer_permission"
            | "pynia.attach"
            | "pynia.tool_reply"
            | "pynia.authenticate"
            | "pynia.inline"
            | "pynia.install"
            | "notifications.settings.get"
            | "notifications.settings.set"
            | "notifications.evaluate"
            | "notifications.send"
            | "notifications.test"
            | "snapshot.settings.get"
            | "snapshot.settings.set"
            | "snapshot.list"
            | "snapshot.save"
            | "snapshot.restore"
            | "snapshot.delete"
            | "workspace.profiles.list"
            | "workspace.profiles.create"
            | "workspace.profiles.rename"
            | "workspace.profiles.clone"
            | "workspace.profiles.delete"
            | "workspace.profiles.restore"
            | "workspace.profiles.select"
            | "workspace.profiles.state"
            | "workspace.profiles.save"
            | "diagnostics.info"
            | "diagnostics.save"
    )
}

struct RuntimeClient {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: Pending,
    next_id: AtomicU64,
    closed: Arc<AtomicBool>,
    #[cfg(windows)]
    _job: windows_job::Job,
}

impl RuntimeClient {
    fn start(app: tauri::AppHandle) -> Result<Self, String> {
        Self::start_with_events(move |message| {
            let _ = app.emit("runtime-event", message);
        })
    }

    fn start_with_events(emit: impl Fn(Value) + Send + 'static) -> Result<Self, String> {
        let mut command = runtime_command()?;
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut child = command.spawn().map_err(|error| {
            format!("Unable to start Python runtime: {error}. Run the desktop development setup.")
        })?;
        #[cfg(windows)]
        let job = match windows_job::Job::assign(&child) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        let stdin = child.stdin.take().ok_or("Python stdin unavailable")?;
        let stdout = child.stdout.take().ok_or("Python stdout unavailable")?;
        let stderr = child.stderr.take().ok_or("Python stderr unavailable")?;
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let closed = Arc::new(AtomicBool::new(false));
        let reader_pending = Arc::clone(&pending);
        let reader_closed = Arc::clone(&closed);
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                match serde_json::from_str::<Value>(&line) {
                    Ok(message) => {
                        if let Some(id) = message.get("id").and_then(Value::as_u64) {
                            let sender = reader_pending
                                .lock()
                                .ok()
                                .and_then(|mut map| map.remove(&id));
                            if let Some(sender) = sender {
                                let result = decode_response(&message);
                                let _ = sender.send(result);
                            }
                        } else if message.get("event").and_then(Value::as_str).is_some() {
                            emit(message);
                        }
                    }
                    Err(_) => {
                        // Never treat stdout text as a response or executable content.
                        eprintln!("DataPyn runtime emitted an invalid protocol message");
                    }
                }
            }
            reader_closed.store(true, Ordering::Release);
            fail_pending(&reader_pending, "Python runtime disconnected");
            emit(
                json!({"event":"backend.exited", "payload":{"message":"Python runtime disconnected"}}),
            );
        });
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("DataPyn runtime: {line}");
            }
        });
        Ok(Self {
            child: Mutex::new(Some(child)),
            stdin: Mutex::new(Some(stdin)),
            pending,
            next_id: AtomicU64::new(1),
            closed,
            #[cfg(windows)]
            _job: job,
        })
    }

    async fn request(self: &Arc<Self>, method: String, params: Value) -> Result<Value, String> {
        if self.closed.load(Ordering::Acquire) {
            return Err("Python runtime disconnected".into());
        }
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let mut bytes = serde_json::to_vec(&json!({"id":id,"method":method,"params":params}))
            .map_err(|error| error.to_string())?;
        if bytes.len() + 1 > MAX_REQUEST_BYTES {
            return Err("Runtime request exceeds 24 MiB".into());
        }
        bytes.push(b'\n');
        let (sender, receiver) = oneshot::channel();
        self.pending
            .lock()
            .map_err(|_| "Runtime requests unavailable")?
            .insert(id, sender);
        let deadline = tokio::time::Instant::now() + REQUEST_TIMEOUT;
        let writer = Arc::clone(self);
        let write_task = tauri::async_runtime::spawn_blocking(move || {
            let mut input = writer
                .stdin
                .lock()
                .map_err(|_| "Python input unavailable")?;
            let stdin = input.as_mut().ok_or("Python runtime stopped")?;
            stdin
                .write_all(&bytes)
                .and_then(|_| stdin.flush())
                .map_err(|error| error.to_string())
        });
        let write_result = match tokio::time::timeout_at(deadline, write_task).await {
            Ok(result) => result.unwrap_or_else(|error| Err(error.to_string())),
            Err(_) => {
                // A stalled transport cannot deliver a later Cancel command.
                // Stop the broker without waiting on the blocked stdin mutex.
                self.closed.store(true, Ordering::Release);
                let stalled = Arc::clone(self);
                let _ = tauri::async_runtime::spawn_blocking(move || stalled.stop()).await;
                Err(
                    "Python transport stalled; the runtime was stopped. Reconnect the runtime."
                        .into(),
                )
            }
        };
        if let Err(error) = write_result {
            if let Ok(mut pending) = self.pending.lock() {
                pending.remove(&id);
            }
            return Err(error);
        }
        match tokio::time::timeout_at(deadline, receiver).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err("Python runtime disconnected".into()),
            Err(_) => {
                if let Ok(mut pending) = self.pending.lock() {
                    pending.remove(&id);
                }
                Err("Python request timed out; the execution may still be running. Use Cancel to stop it.".into())
            }
        }
    }

    fn stop(&self) {
        self.closed.store(true, Ordering::Release);
        // write_all may hold this lock while the broker stops reading. Never
        // wait for it here: killing the child below also releases that writer.
        if let Ok(mut input) = self.stdin.try_lock() {
            input.take();
        }
        fail_pending(&self.pending, "Python runtime stopped");
        if let Ok(mut process) = self.child.lock() {
            if let Some(mut child) = process.take() {
                let deadline = Instant::now() + Duration::from_secs(3);
                loop {
                    match child.try_wait() {
                        Ok(Some(_)) => break,
                        _ if Instant::now() < deadline => thread::sleep(Duration::from_millis(20)),
                        _ => {
                            #[cfg(windows)]
                            self._job.terminate();
                            let _ = child.kill();
                            let _ = child.wait();
                            break;
                        }
                    }
                }
            }
        }
        // A descendant may retain the pipe even after the supervisor exits.
        // Terminate the group explicitly; a blocked writer holds an Arc and
        // would otherwise postpone the job handle's Drop indefinitely.
        #[cfg(windows)]
        self._job.terminate();
    }
}

impl Drop for RuntimeClient {
    fn drop(&mut self) {
        self.stop();
    }
}

fn decode_response(message: &Value) -> Result<Value, String> {
    if let Some(error) = message.get("error") {
        Err(error
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("Python request failed")
            .to_owned())
    } else {
        message
            .get("result")
            .cloned()
            .ok_or_else(|| "Python response missing result".to_owned())
    }
}

fn fail_pending(pending: &Pending, error: &str) {
    if let Ok(mut map) = pending.lock() {
        for (_, sender) in map.drain() {
            let _ = sender.send(Err(error.to_owned()));
        }
    }
}

fn runtime_command() -> Result<Command, String> {
    #[cfg(debug_assertions)]
    {
        use std::path::{Path, PathBuf};
        let repo = std::env::var_os("DATAPYN_REPO_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../..")
                    .to_path_buf()
            });
        let python = std::env::var_os("DATAPYN_RUNTIME_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                repo.join(if cfg!(windows) {
                    ".venv/Scripts/python.exe"
                } else {
                    ".venv/bin/python"
                })
            });
        if !python.is_file() {
            return Err(format!(
                "Python environment not found at {}. Run uv sync --dev in the repository.",
                python.display()
            ));
        }
        let mut command = Command::new(python);
        command.args(["-u", "-m", "datapyn_runtime"]);
        command.current_dir(&repo);
        let mut paths = vec![repo.join("source")];
        if let Some(existing) = std::env::var_os("PYTHONPATH") {
            paths.extend(std::env::split_paths(&existing));
        }
        command.env(
            "PYTHONPATH",
            std::env::join_paths(paths).map_err(|error| error.to_string())?,
        );
        command.env("PYTHONUTF8", "1");
        Ok(command)
    }
    #[cfg(not(debug_assertions))]
    {
        let executable = std::env::current_exe().map_err(|error| error.to_string())?;
        let parent = executable
            .parent()
            .ok_or("Desktop executable directory unavailable")?;
        let runtime = parent.join(if cfg!(windows) {
            "datapyn-runtime.exe"
        } else {
            "datapyn-runtime"
        });
        if !runtime.is_file() {
            return Err(
                "Bundled Python runtime is missing. Build with the sidecar bundle configuration."
                    .into(),
            );
        }
        let mut command = Command::new(runtime);
        command.env("PYTHONUTF8", "1");
        Ok(command)
    }
}

#[cfg(windows)]
mod windows_job {
    use std::{mem, os::windows::io::AsRawHandle, process::Child, ptr};
    use windows_sys::Win32::{
        Foundation::{CloseHandle, HANDLE},
        System::JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
    };

    pub struct Job(HANDLE);
    // Windows job handles are process-wide and may be closed from any thread.
    // The handle is owned by this object and remains valid until Drop.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}
    impl Job {
        pub fn terminate(&self) {
            unsafe {
                let _ = TerminateJobObject(self.0, 1);
            }
        }

        pub fn assign(child: &Child) -> Result<Self, String> {
            unsafe {
                let handle = CreateJobObjectW(ptr::null(), ptr::null());
                if handle.is_null() {
                    return Err(format!(
                        "Unable to create runtime process group: {}",
                        std::io::Error::last_os_error()
                    ));
                }
                let job = Self(handle);
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    mem::size_of_val(&info) as u32,
                ) == 0
                    || AssignProcessToJobObject(handle, child.as_raw_handle()) == 0
                {
                    return Err(format!(
                        "Unable to supervise runtime process group: {}",
                        std::io::Error::last_os_error()
                    ));
                }
                Ok(job)
            }
        }
    }
    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(client: &Arc<RuntimeClient>, method: &str, params: Value) -> Value {
        tauri::async_runtime::block_on(client.request(method.into(), params)).unwrap()
    }

    fn event(
        events: &std::sync::mpsc::Receiver<Value>,
        name: &str,
        execution_id: Option<&str>,
    ) -> Value {
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            let message = events
                .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                .expect("Python event deadline exceeded");
            if message["event"] == name
                && execution_id.map_or(true, |id| message["payload"]["execution_id"] == id)
            {
                return message["payload"].clone();
            }
        }
    }

    #[test]
    fn real_python_transport_preserves_sql_python_and_session_isolation() {
        let (sender, events) = std::sync::mpsc::channel();
        let client = Arc::new(
            RuntimeClient::start_with_events(move |message| {
                let _ = sender.send(message);
            })
            .unwrap(),
        );
        assert_eq!(
            request(&client, "system.info", json!({}))["protocol_version"],
            1
        );
        let first = request(&client, "session.create", json!({}))["session_id"].clone();
        request(
            &client,
            "connection.connect",
            json!({"session_id":first,"config":{"db_type":"sqlite","database":":memory:"}}),
        );
        request(
            &client,
            "execution.run",
            json!({"session_id":first,"execution_id":"sql","language":"sql","code":"SELECT 21 AS value","variable_name":"df"}),
        );
        assert_eq!(
            event(&events, "execution.finished", Some("sql"))["status"],
            "succeeded"
        );
        request(
            &client,
            "execution.run",
            json!({"session_id":first,"execution_id":"python","language":"python","code":"df.assign(value=df.value * 2)"}),
        );
        let finished = event(&events, "execution.finished", Some("python"));
        assert_eq!(finished["status"], "succeeded");
        let handle = finished["results"][0]["result_id"].clone();
        let page = request(
            &client,
            "result.page",
            json!({"session_id":first,"result_id":handle,"offset":0,"limit":10}),
        );
        assert_eq!(page["rows"][0][0], 42);

        let second = request(&client, "session.create", json!({}))["session_id"].clone();
        request(
            &client,
            "execution.run",
            json!({"session_id":first,"execution_id":"loop","language":"python","code":"while True:\n    pass"}),
        );
        event(&events, "execution.started", Some("loop"));
        request(
            &client,
            "execution.run",
            json!({"session_id":second,"execution_id":"independent","language":"python","code":"pd.DataFrame({'value': [7]})"}),
        );
        assert_eq!(
            event(&events, "execution.finished", Some("independent"))["status"],
            "succeeded"
        );
        request(
            &client,
            "execution.cancel",
            json!({"session_id":first,"execution_id":"loop"}),
        );
        assert_eq!(
            event(&events, "session.reset", None)["namespace_lost"],
            true
        );
        request(
            &client,
            "execution.run",
            json!({"session_id":first,"execution_id":"recovered","language":"python","code":"pd.DataFrame({'value': [9]})"}),
        );
        assert_eq!(
            event(&events, "execution.finished", Some("recovered"))["status"],
            "succeeded"
        );
        assert!(tauri::async_runtime::block_on(client.request(
            "result.page".into(),
            json!({"session_id":first,"result_id":handle,"offset":0,"limit":10})
        ))
        .is_err());
        client.stop();
    }

    #[test]
    fn shutdown_does_not_wait_for_a_held_input_mutex() {
        let client = Arc::new(RuntimeClient::start_with_events(|_| {}).unwrap());
        let held = Arc::clone(&client);
        let (ready, waiting) = std::sync::mpsc::channel();
        let (release, released) = std::sync::mpsc::channel();
        let writer = thread::spawn(move || {
            let _input = held.stdin.lock().unwrap();
            ready.send(()).unwrap();
            let _ = released.recv_timeout(Duration::from_secs(8));
        });
        waiting.recv_timeout(Duration::from_secs(5)).unwrap();
        let started = Instant::now();
        client.stop();
        let elapsed = started.elapsed();
        let _ = release.send(());
        writer.join().unwrap();
        assert!(
            elapsed < Duration::from_secs(5),
            "shutdown waited for input: {elapsed:?}"
        );
        assert!(client.child.lock().unwrap().is_none());
    }

    #[test]
    fn malformed_and_error_responses_do_not_become_success() {
        assert_eq!(
            decode_response(&json!({"result":{"ok":true}})).unwrap(),
            json!({"ok":true})
        );
        assert!(decode_response(&json!({"id":1})).is_err());
        assert_eq!(
            decode_response(&json!({"error":{"message":"invalid session"}})).unwrap_err(),
            "invalid session"
        );
    }
    #[test]
    fn native_bridge_only_exposes_runtime_contract() {
        assert!(allowed_method("execution.cancel"));
        assert!(allowed_method("workspace.read"));
        assert!(!allowed_method("shell.execute"));
        assert!(!allowed_method(""));
    }
}
