mod execution_notifications;
#[cfg(windows)]
mod notification_activator;
#[cfg(windows)]
mod notification_identity;
mod runtime;
mod updater_channel;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Mutex,
    },
};
use tauri::{Emitter, Manager, State};

const WEBVIEW_CONTEXT_MENU_SCRIPT: &str = include_str!("../../public/webview-context-menu.js");

#[derive(Default)]
struct StartupFiles(Mutex<Vec<String>>);

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum SplashPhase {
    Frontend,
    Runtime,
    Workspace,
    Editor,
    Ready,
    Error,
}

impl SplashPhase {
    fn rank(&self) -> u8 {
        match self {
            Self::Frontend => 0,
            Self::Runtime => 1,
            Self::Workspace => 2,
            Self::Editor => 3,
            Self::Ready | Self::Error => 4,
        }
    }
}

#[derive(Clone, Debug, Serialize)]
struct SplashSnapshot {
    phase: SplashPhase,
    message: String,
    attempt: u64,
    version: String,
}

impl SplashSnapshot {
    fn new(version: String) -> Self {
        Self {
            phase: SplashPhase::Frontend,
            message: "Preparando seu ambiente de trabalho…".into(),
            attempt: 0,
            version,
        }
    }

    fn accepts(&self, phase: &SplashPhase, attempt: Option<u64>) -> bool {
        attempt.map_or(true, |attempt| attempt == self.attempt)
            && !matches!(self.phase, SplashPhase::Ready | SplashPhase::Error)
            && phase.rank() >= self.phase.rank()
    }

    fn retry(&mut self) -> bool {
        if self.phase != SplashPhase::Error {
            return false;
        }
        self.attempt += 1;
        self.phase = SplashPhase::Runtime;
        self.message = "Iniciando novamente…".into();
        true
    }
}

struct SplashLifecycle {
    latest: Mutex<SplashSnapshot>,
    exiting: AtomicBool,
    publishing: tokio::sync::Mutex<()>,
}

fn buffer_startup_files(
    latest: &Mutex<SplashSnapshot>,
    queue: &Mutex<Vec<String>>,
    files: &mut Vec<String>,
) -> Result<bool, String> {
    // Keep the startup-state lock until files are queued. Publishing ready
    // takes the same lock before draining the queue, so a concurrent second
    // launch cannot enqueue behind that final drain.
    let state = latest.lock().map_err(|_| "Startup state unavailable")?;
    if state.phase == SplashPhase::Ready {
        return Ok(false);
    }
    queue
        .lock()
        .map_err(|_| "Startup files unavailable")?
        .append(files);
    Ok(true)
}

fn local_asset(url: &tauri::Url, path: &str, development_origin: Option<&tauri::Url>) -> bool {
    if url.path() != path || !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    let asset = (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
        || (matches!(url.scheme(), "http" | "https")
            && url.host_str() == Some("tauri.localhost")
            && url.port().is_none());
    asset || development_origin.is_some_and(|origin| origin.origin() == url.origin())
}

fn popout_outer_position(position: Option<tauri::LogicalPosition<f64>>) -> Option<tauri::Position> {
    // window.open and screenX/screenY use logical screen coordinates. Preserve
    // that unit so Tauri resolves the target monitor's DPI without frame offsets.
    position
        .filter(|position| position.x.is_finite() && position.y.is_finite())
        .map(tauri::Position::Logical)
}

fn native_popout_label(label: &str) -> bool {
    label.strip_prefix("dock-popout-").is_some_and(|suffix| {
        !suffix.is_empty() && suffix.bytes().all(|byte| byte.is_ascii_digit())
    })
}

#[derive(Debug, PartialEq, Serialize)]
struct NativePopoutLayout {
    left: f64,
    top: f64,
    width: f64,
    height: f64,
}

fn logical_popout_layout(
    position: tauri::PhysicalPosition<i32>,
    size: tauri::PhysicalSize<u32>,
    scale: f64,
) -> Option<NativePopoutLayout> {
    if !scale.is_finite() || scale <= 0.0 || size.width == 0 || size.height == 0 {
        return None;
    }
    let position = position.to_logical::<f64>(scale);
    let size = size.to_logical::<f64>(scale);
    Some(NativePopoutLayout {
        left: position.x,
        top: position.y,
        width: size.width,
        height: size.height,
    })
}

#[tauri::command]
fn popout_layout(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
) -> Result<std::collections::BTreeMap<String, NativePopoutLayout>, String> {
    require_local_window(&window, &["main"])?;
    let origin = if cfg!(debug_assertions) {
        app.config().build.dev_url.as_ref()
    } else {
        None
    };
    let mut layouts = std::collections::BTreeMap::new();
    for (label, popout) in app.webview_windows() {
        if !native_popout_label(&label) || !popout.url().is_ok_and(|url| local_popout(&url, origin))
        {
            continue;
        }
        // A window can disappear during a close notification; omit it safely.
        if let (Ok(position), Ok(size), Ok(scale)) = (
            popout.outer_position(),
            popout.inner_size(),
            popout.scale_factor(),
        ) {
            if let Some(layout) = logical_popout_layout(position, size, scale) {
                layouts.insert(label, layout);
            }
        }
    }
    Ok(layouts)
}

#[tauri::command]
fn close_popout(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    label: String,
) -> Result<(), String> {
    require_local_window(&window, &["main"])?;
    if !native_popout_label(&label) {
        return Err("Only DataPyn panel windows can be closed".into());
    }
    let Some(popout) = app.get_webview_window(&label) else {
        return Ok(());
    };
    let origin = if cfg!(debug_assertions) {
        app.config().build.dev_url.as_ref()
    } else {
        None
    };
    if !popout
        .url()
        .is_ok_and(|url| url.as_str() == "about:blank" || local_popout(&url, origin))
    {
        return Err("Only the local DataPyn panel can be closed".into());
    }
    popout.destroy().map_err(|error| error.to_string())
}

/// Called immediately after building each window, on Tauri's native UI thread.
fn disable_browser_actions(window: &tauri::WebviewWindow) -> Result<(), String> {
    #[cfg(windows)]
    {
        use webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Settings3;
        use windows_core::Interface;

        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        window
            .with_webview(move |webview| {
                // Disable WebView2's built-in menu, including over frames. Page
                // contextmenu events remain available to DataPyn's custom menus.
                // WebView2 also intercepts F5/Ctrl+R before DOM preventDefault;
                // keep DOM key events and text editing while disabling those actions.
                // SAFETY: Tauri runs this closure on the controller's COM/UI thread.
                let result = unsafe {
                    (|| -> windows_core::Result<(bool, bool)> {
                        let settings = webview.controller().CoreWebView2()?.Settings()?;
                        settings.SetAreDefaultContextMenusEnabled(false)?;
                        let mut context_menus_enabled = windows_core::BOOL(1);
                        settings.AreDefaultContextMenusEnabled(&mut context_menus_enabled)?;
                        let settings = settings.cast::<ICoreWebView2Settings3>()?;
                        settings.SetAreBrowserAcceleratorKeysEnabled(false)?;
                        let mut accelerators_enabled = windows_core::BOOL(1);
                        settings.AreBrowserAcceleratorKeysEnabled(&mut accelerators_enabled)?;
                        Ok((
                            context_menus_enabled.as_bool(),
                            accelerators_enabled.as_bool(),
                        ))
                    })()
                }
                .map_err(|error| error.to_string())
                .and_then(|(context_menus_enabled, accelerators_enabled)| {
                    if context_menus_enabled {
                        Err("WebView2 did not disable default context menus".into())
                    } else if accelerators_enabled {
                        Err("WebView2 did not disable browser accelerator keys".into())
                    } else {
                        Ok(())
                    }
                });
                let _ = sender.send(result);
            })
            .map_err(|error| error.to_string())?;
        // with_webview executes synchronously on the native UI thread. Avoid a
        // blocking wait if this function is accidentally moved to another thread.
        receiver
            .try_recv()
            .map_err(|_| "Native browser setup must run on the UI thread".to_string())?
    }
    #[cfg(not(windows))]
    {
        let _ = window;
        Ok(())
    }
}

fn require_local_window(window: &tauri::WebviewWindow, labels: &[&str]) -> Result<(), String> {
    if !labels.contains(&window.label()) {
        return Err("This window cannot use this command".into());
    }
    let url = window.url().map_err(|error| error.to_string())?;
    let origin = if cfg!(debug_assertions) {
        window.app_handle().config().build.dev_url.as_ref()
    } else {
        None
    };
    let paths: &[&str] = match window.label() {
        "main" => &["/", "/index.html"],
        "splash" => &["/splash.html"],
        _ => &[],
    };
    if paths.iter().any(|path| local_asset(&url, path, origin)) {
        Ok(())
    } else {
        Err("Only the local DataPyn interface can use this command".into())
    }
}

#[tauri::command]
fn splash_state(
    window: tauri::WebviewWindow,
    state: State<'_, SplashLifecycle>,
) -> Result<SplashSnapshot, String> {
    require_local_window(&window, &["main", "splash"])?;
    state
        .latest
        .lock()
        .map(|state| state.clone())
        .map_err(|_| "Startup state unavailable".into())
}

#[tauri::command]
async fn splash_publish(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, SplashLifecycle>,
    phase: SplashPhase,
    message: Option<String>,
    attempt: Option<u64>,
) -> Result<SplashSnapshot, String> {
    require_local_window(&window, &["main"])?;
    let _publishing = state.publishing.lock().await;
    let mut snapshot = {
        let latest = state
            .latest
            .lock()
            .map_err(|_| "Startup state unavailable")?;
        if !latest.accepts(&phase, attempt) {
            return Ok(latest.clone());
        }
        latest.clone()
    };
    snapshot.phase = phase;
    if let Some(message) = message {
        snapshot.message = message.chars().take(2000).collect();
    }
    if snapshot.phase == SplashPhase::Ready {
        let show = app
            .get_webview_window("main")
            .ok_or_else(|| "Main window unavailable".to_string())
            .and_then(|main| {
                main.show().map_err(|error| error.to_string())?;
                main.set_focus().map_err(|error| error.to_string())
            });
        if let Err(error) = show {
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.hide();
            }
            snapshot.phase = SplashPhase::Error;
            snapshot.message = format!("Não foi possível abrir a janela principal: {error}");
        }
    }
    {
        let mut latest = state
            .latest
            .lock()
            .map_err(|_| "Startup state unavailable")?;
        // A retry may have started while native window operations were queued.
        if latest.attempt != snapshot.attempt
            || matches!(latest.phase, SplashPhase::Ready | SplashPhase::Error)
        {
            return Ok(latest.clone());
        }
        *latest = snapshot.clone();
    }
    if let Some(splash) = app.get_webview_window("splash") {
        let _ = splash.emit("splash-state", &snapshot);
        if snapshot.phase == SplashPhase::Ready {
            let _ = splash.destroy();
        }
    }
    if snapshot.phase == SplashPhase::Ready {
        // Files from a second launch are buffered until React has restored its
        // workspace and installed its open-files listener.
        let files = app.state::<StartupFiles>();
        if let Ok(mut queue) = files.0.lock() {
            if !queue.is_empty() {
                let files = std::mem::take(&mut *queue);
                let _ = window.emit("datapyn-open-files", files);
            }
        };
    }
    Ok(snapshot)
}

#[tauri::command]
fn splash_retry(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, SplashLifecycle>,
) -> Result<SplashSnapshot, String> {
    require_local_window(&window, &["splash"])?;
    let (mut snapshot, retry) = {
        let mut latest = state
            .latest
            .lock()
            .map_err(|_| "Startup state unavailable")?;
        let retry = latest.retry();
        (latest.clone(), retry)
    };
    if retry {
        let _ = window.emit("splash-state", &snapshot);
        let delivered = app
            .get_webview_window("main")
            .ok_or_else(|| "Main window unavailable".to_string())
            .and_then(|main| {
                main.emit("splash-retry", &snapshot)
                    .map_err(|error| error.to_string())
            });
        if let Err(error) = delivered {
            snapshot.phase = SplashPhase::Error;
            snapshot.message = format!("Não foi possível reiniciar a interface: {error}");
            *state
                .latest
                .lock()
                .map_err(|_| "Startup state unavailable")? = snapshot.clone();
            let _ = window.emit("splash-state", &snapshot);
        }
    }
    Ok(snapshot)
}

#[tauri::command]
fn splash_exit(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, SplashLifecycle>,
) -> Result<(), String> {
    require_local_window(&window, &["splash"])?;
    state.exiting.store(true, Ordering::Release);
    app.exit(0);
    Ok(())
}

fn local_popout(url: &tauri::Url, development_origin: Option<&tauri::Url>) -> bool {
    local_asset(url, "/popout.html", development_origin)
}

fn collect_files(args: &[String], cwd: &str) -> Vec<String> {
    args.iter()
        .skip(1)
        .filter_map(|arg| {
            let path = PathBuf::from(arg);
            let resolved = if path.is_absolute() {
                path
            } else {
                PathBuf::from(cwd).join(path)
            };
            resolved
                .canonicalize()
                .ok()
                .filter(|path| path.is_file())
                .map(|path| {
                    let value = path.to_string_lossy().to_string();
                    value.strip_prefix("\\\\?\\").unwrap_or(&value).to_string()
                })
        })
        .collect()
}

#[cfg(any(target_os = "macos", test))]
fn collect_opened_files(urls: &[tauri::Url]) -> Vec<String> {
    let mut args = vec!["datapyn-desktop".to_string()];
    args.extend(urls.iter().filter_map(|url| {
        // Finder supplies percent-encoded file URLs. Never route web/deep-link URLs
        // to the document loader as filesystem paths.
        url.to_file_path()
            .ok()
            .map(|path| path.to_string_lossy().to_string())
    }));
    collect_files(&args, "")
}

fn dispatch_open_files(app: &tauri::AppHandle, mut files: Vec<String>) {
    let state = app.state::<SplashLifecycle>();
    let queued = buffer_startup_files(&state.latest, &app.state::<StartupFiles>().0, &mut files)
        .unwrap_or(true);
    if queued {
        if let Some(window) = app.get_webview_window("splash") {
            let _ = window.show();
            let _ = window.set_focus();
        }
        return;
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
    let _ = app.emit("datapyn-open-files", files);
}

#[tauri::command]
fn startup_files(
    window: tauri::WebviewWindow,
    state: State<'_, StartupFiles>,
) -> Result<Vec<String>, String> {
    require_local_window(&window, &["main"])?;
    let mut paths = state.0.lock().map_err(|_| "Startup files unavailable")?;
    Ok(std::mem::take(&mut *paths))
}

use updater_channel::update_status;

#[tauri::command]
fn updater_status(app: tauri::AppHandle) -> Value {
    let status = update_status(
        app.config()
            .plugins
            .0
            .get("updater")
            .unwrap_or(&Value::Null),
        &app.package_info().version.to_string(),
    );
    #[cfg(windows)]
    {
        if tauri::utils::platform::current_exe()
            .ok()
            .and_then(|path| updater_channel::windows_installer_directory(&path))
            .is_none()
        {
            let mut status = status;
            status["available"] = serde_json::json!(false);
            status["automatic_download"] = serde_json::json!(false);
            status["reason"] = serde_json::json!("Não foi possível determinar a pasta desta instalação para atualizar o DataPyn Tauri.");
            return status;
        }
    }
    #[cfg(target_os = "linux")]
    {
        if std::env::var_os("APPIMAGE").is_none() {
            let mut status = status;
            status["available"] = serde_json::json!(false);
            status["automatic_download"] = serde_json::json!(false);
            status["reason"] = serde_json::json!("No Linux, abra o DataPyn pelo AppImage ou pelo launcher do pacote para usar atualizações automáticas.");
            return status;
        }
    }
    status
}

#[tauri::command]
async fn backend_request(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, runtime::Backend>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    require_local_window(&window, &["main"])?;
    state
        .request(app, method, params.unwrap_or_else(|| serde_json::json!({})))
        .await
}

pub fn run() {
    let updater = tauri_plugin_updater::Builder::new();
    #[cfg(windows)]
    let updater = match tauri::utils::platform::current_exe()
        .ok()
        .and_then(|path| updater_channel::windows_installer_directory(&path))
    {
        Some(directory) => updater.installer_arg(directory),
        None => updater,
    };
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, cwd| {
            dispatch_open_files(app, collect_files(&args, &cwd));
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(updater.build())
        .plugin(tauri_plugin_process::init())
        .manage(StartupFiles(Mutex::new(collect_files(
            &std::env::args().collect::<Vec<_>>(),
            &std::env::current_dir()
                .unwrap_or_default()
                .to_string_lossy(),
        ))))
        .manage(runtime::Backend::default())
        .manage(execution_notifications::NativeNotifications::default())
        .manage(SplashLifecycle {
            latest: Mutex::new(SplashSnapshot::new(env!("CARGO_PKG_VERSION").into())),
            exiting: AtomicBool::new(false),
            publishing: tokio::sync::Mutex::new(()),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            let origin = if cfg!(debug_assertions) {
                app.config().build.dev_url.clone()
            } else {
                None
            };
            let windows = AtomicUsize::new(0);
            let splash_config = app
                .config()
                .app
                .windows
                .iter()
                .find(|config| config.label == "splash")
                .ok_or("Splash window configuration is unavailable")?;
            let splash = tauri::WebviewWindowBuilder::from_config(app, splash_config)?
                .initialization_script_for_all_frames(WEBVIEW_CONTEXT_MENU_SCRIPT)
                .on_navigation({
                    let origin = origin.clone();
                    move |url| local_asset(url, "/splash.html", origin.as_ref())
                })
                .build()?;
            disable_browser_actions(&splash).map_err(std::io::Error::other)?;
            let config = app
                .config()
                .app
                .windows
                .iter()
                .find(|config| config.label == "main")
                .ok_or("Main window configuration is unavailable")?;
            let main = tauri::WebviewWindowBuilder::from_config(app, config)?
                .visible(false)
                .initialization_script_for_all_frames(WEBVIEW_CONTEXT_MENU_SCRIPT)
                .on_new_window(move |url, features| {
                    if !local_popout(&url, origin.as_ref()) {
                        return tauri::webview::NewWindowResponse::Deny;
                    }
                    let outer_position = popout_outer_position(features.position());
                    let label = format!("dock-popout-{}", windows.fetch_add(1, Ordering::Relaxed));
                    let label_script = format!(
                        "Object.defineProperty(window,'__DATAPYN_NATIVE_LABEL__',{{value:{},writable:false,configurable:false}});",
                        serde_json::to_string(&label).unwrap()
                    );
                    match tauri::WebviewWindowBuilder::new(
                        &handle,
                        label,
                        tauri::WebviewUrl::External("about:blank".parse().unwrap()),
                    )
                    .window_features(features)
                    .initialization_script_for_all_frames(WEBVIEW_CONTEXT_MENU_SCRIPT)
                    .initialization_script(label_script)
                    .on_navigation({
                        let origin = origin.clone();
                        move |url| {
                            url.as_str() == "about:blank" || local_popout(url, origin.as_ref())
                        }
                    })
                    .on_document_title_changed(|window, title| {
                        let _ = window.set_title(&title);
                    })
                    .title("DataPyn")
                    .build()
                    {
                        Ok(window) => {
                            if let Err(error) = disable_browser_actions(&window) {
                                let _ = window.close();
                                let _ = handle.emit("datapyn-popout-error", error);
                                return tauri::webview::NewWindowResponse::Deny;
                            }
                            // Builders can interpret position as the content origin.
                            // Dockview serializes the outer origin; reapply it through
                            // Tauri's outer-position API after decorations exist.
                            if let Some(position) = outer_position {
                                if let Err(error) = window.set_position(position) {
                                    let _ = handle.emit("datapyn-popout-error", error.to_string());
                                }
                            }
                            tauri::webview::NewWindowResponse::Create { window }
                        }
                        Err(error) => {
                            let _ = handle.emit("datapyn-popout-error", error.to_string());
                            tauri::webview::NewWindowResponse::Deny
                        }
                    }
                })
                .build()?;
            disable_browser_actions(&main).map_err(std::io::Error::other)?;
            // A closed preview process cannot route old immutable toast targets.
            app.state::<execution_notifications::NativeNotifications>().initialize(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_request,
            startup_files,
            updater_status,
            splash_state,
            splash_publish,
            splash_retry,
            splash_exit,
            popout_layout,
            close_popout,
            execution_notifications::execution_notification_show,
            execution_notifications::execution_notification_take_pending,
            execution_notifications::execution_notification_ack,
            execution_notifications::execution_notification_focus_window
        ])
        .build(tauri::generate_context!())
        .expect("Unable to initialize the DataPyn desktop host");

    app.run(|app, event| {
        #[cfg(target_os = "macos")]
        {
            if let tauri::RunEvent::Opened { urls } = &event {
                dispatch_open_files(app, collect_opened_files(urls));
            }
            if matches!(&event, tauri::RunEvent::Reopen { .. }) {
                dispatch_open_files(app, Vec::new());
            }
        }
        if let tauri::RunEvent::WindowEvent { label, event: tauri::WindowEvent::CloseRequested { api, .. }, .. } = &event {
            if label == "splash" {
                api.prevent_close();
                app.state::<SplashLifecycle>().exiting.store(true, Ordering::Release);
                app.exit(0);
            }
        }
        if matches!(&event, tauri::RunEvent::WindowEvent {label,event:tauri::WindowEvent::Destroyed,..} if label == "main") {
            for (label, window) in app.webview_windows() {
                if label.starts_with("dock-popout-") || label == "splash" { let _ = window.destroy(); }
            }
        }
        if matches!(&event, tauri::RunEvent::WindowEvent {label,event:tauri::WindowEvent::Destroyed,..} if label == "splash") {
            let state = app.state::<SplashLifecycle>();
            let ready = state.latest.lock().map(|snapshot| snapshot.phase == SplashPhase::Ready).unwrap_or(false);
            if !ready {
                state.exiting.store(true, Ordering::Release);
                app.exit(0);
            }
        }
        if matches!(event, tauri::RunEvent::Exit) {
            app.state::<execution_notifications::NativeNotifications>().shutdown();
            // Cancelling startup must not wait for a request that holds the
            // runtime client mutex. Process exit closes the broker pipe and
            // Windows' KILL_ON_JOB_CLOSE handle, including owned kernels.
            if !app.state::<SplashLifecycle>().exiting.load(Ordering::Acquire) {
                app.state::<runtime::Backend>().shutdown();
            }
        }
    });
}

#[cfg(test)]
mod update_tests {
    use super::updater_channel;
    use super::{
        buffer_startup_files, collect_opened_files, local_asset, local_popout,
        logical_popout_layout, native_popout_label, popout_outer_position, update_status,
        SplashPhase, SplashSnapshot,
    };
    use serde_json::json;
    use std::sync::{Arc, Barrier, Mutex};

    #[test]
    fn finder_file_urls_decode_unicode_and_spaces_and_ignore_remote_urls() {
        let path = std::env::temp_dir().join(format!(
            "datapyn-finder-{}-Análise com espaços.dpw",
            std::process::id()
        ));
        std::fs::write(&path, "{}").unwrap();
        let local = tauri::Url::from_file_path(&path).unwrap();
        let remote = "https://example.com/analysis.dpw".parse().unwrap();
        let missing = tauri::Url::from_file_path(path.with_extension("missing")).unwrap();
        let files = collect_opened_files(&[local, remote, missing]);
        let canonical = path.canonicalize().unwrap().to_string_lossy().to_string();
        assert_eq!(
            files,
            vec![canonical
                .strip_prefix("\\\\?\\")
                .unwrap_or(&canonical)
                .to_string()]
        );
        std::fs::remove_file(&path).unwrap();
    }

    #[test]
    fn unsigned_or_non_tls_channels_are_unavailable() {
        for config in [
            json!({}),
            json!({"pubkey":"public","endpoints":[]}),
            json!({"pubkey":"public","endpoints":["http://example.com/latest.json"]}),
        ] {
            assert_eq!(update_status(&config, "1.57.0")["available"], false);
        }
        let status = update_status(
            &json!({"pubkey":"public","endpoints":[updater_channel::ENDPOINT]}),
            "1.57.0",
        );
        assert_eq!(status["available"], true);
        assert_eq!(status["channel"], "tauri-stable");
    }

    #[test]
    fn popout_rejects_external_origins_and_other_assets() {
        let origin = "http://localhost:1420".parse().unwrap();
        for address in [
            "http://localhost:1420/popout.html?group=1",
            "tauri://localhost/popout.html",
            "http://tauri.localhost/popout.html",
        ] {
            assert!(local_popout(&address.parse().unwrap(), Some(&origin)));
        }
        for address in [
            "https://example.com/popout.html",
            "http://localhost:1421/popout.html",
            "http://localhost:1420/index.html",
            "http://user@localhost:1420/popout.html",
            "file:///popout.html",
            "javascript:alert(1)",
        ] {
            assert!(!local_popout(&address.parse().unwrap(), Some(&origin)));
        }
        assert!(!local_popout(
            &"http://localhost:1420/popout.html".parse().unwrap(),
            None
        ));
    }

    #[test]
    fn popout_position_keeps_outer_coordinates_and_logical_dpi_units() {
        for (x, y) in [(377.0, 659.0), (-1230.0, -410.0), (377.5, 659.25)] {
            let requested = tauri::LogicalPosition::new(x, y);
            let position = popout_outer_position(Some(requested)).unwrap();
            assert!(matches!(position, tauri::Position::Logical(value) if value == requested));
            let physical: tauri::PhysicalPosition<i32> = position.to_physical(1.5);
            assert_eq!(physical, requested.to_physical(1.5));
        }
    }

    #[test]
    fn popout_position_rejects_non_finite_coordinates_and_omitted_positions() {
        assert!(popout_outer_position(None).is_none());
        for (x, y) in [
            (f64::NAN, 0.0),
            (0.0, f64::INFINITY),
            (f64::NEG_INFINITY, 0.0),
        ] {
            assert!(popout_outer_position(Some(tauri::LogicalPosition::new(x, y))).is_none());
        }
    }

    #[test]
    fn native_popout_geometry_uses_outer_origin_and_client_size_in_logical_pixels() {
        let layout = logical_popout_layout(
            tauri::PhysicalPosition::new(-2400, 1320),
            tauri::PhysicalSize::new(1690, 620),
            2.0,
        )
        .unwrap();
        assert_eq!(layout.left, -1200.0);
        assert_eq!(layout.top, 660.0);
        assert_eq!(layout.width, 845.0);
        assert_eq!(layout.height, 310.0);
        assert!(logical_popout_layout(
            tauri::PhysicalPosition::new(0, 0),
            tauri::PhysicalSize::new(0, 0),
            1.0
        )
        .is_none());
        assert!(logical_popout_layout(
            tauri::PhysicalPosition::new(0, 0),
            tauri::PhysicalSize::new(845, 310),
            f64::NAN
        )
        .is_none());
    }

    #[test]
    fn native_popout_commands_reject_main_splash_and_non_panel_labels() {
        assert!(native_popout_label("dock-popout-0"));
        assert!(native_popout_label("dock-popout-123"));
        for label in [
            "main",
            "splash",
            "dock-popout-",
            "dock-popout-main",
            "other-window",
        ] {
            assert!(!native_popout_label(label));
        }
    }

    #[test]
    fn startup_progress_is_monotonic_and_ready_is_terminal() {
        let mut state = SplashSnapshot::new("1.57.0".into());
        for phase in [
            SplashPhase::Runtime,
            SplashPhase::Workspace,
            SplashPhase::Editor,
            SplashPhase::Ready,
        ] {
            assert!(state.accepts(&phase, Some(0)));
            state.phase = phase;
        }
        assert!(!state.accepts(&SplashPhase::Runtime, Some(0)));
        assert!(!state.accepts(&SplashPhase::Error, Some(0)));
        assert!(!state.retry());
    }

    #[test]
    fn failed_startup_requires_explicit_retry_and_rejects_stale_updates() {
        let mut state = SplashSnapshot::new("1.57.0".into());
        state.phase = SplashPhase::Workspace;
        assert!(!state.accepts(&SplashPhase::Runtime, Some(0)));
        assert!(state.accepts(&SplashPhase::Error, Some(0)));
        state.phase = SplashPhase::Error;
        assert!(!state.accepts(&SplashPhase::Ready, Some(0)));
        assert!(state.retry());
        assert_eq!(state.attempt, 1);
        assert_eq!(state.phase, SplashPhase::Runtime);
        assert!(!state.accepts(&SplashPhase::Ready, Some(0)));
        assert!(state.accepts(&SplashPhase::Workspace, Some(1)));
        assert!(!state.retry());
    }

    #[test]
    fn splash_snapshot_contains_status_and_build_version() {
        let state = serde_json::to_value(SplashSnapshot::new("1.57.0".into())).unwrap();
        assert_eq!(state["phase"], "frontend");
        assert_eq!(state["attempt"], 0);
        assert_eq!(state["version"], "1.57.0");
        assert!(state["message"]
            .as_str()
            .is_some_and(|message| !message.is_empty()));
    }

    #[test]
    fn splash_only_accepts_its_local_entrypoint() {
        let origin = "http://localhost:1420".parse().unwrap();
        for address in [
            "http://localhost:1420/splash.html",
            "tauri://localhost/splash.html",
            "http://tauri.localhost/splash.html",
        ] {
            assert!(local_asset(
                &address.parse().unwrap(),
                "/splash.html",
                Some(&origin)
            ));
        }
        for address in [
            "https://example.com/splash.html",
            "http://localhost:1421/splash.html",
            "http://localhost:1420/",
            "http://user@localhost:1420/splash.html",
            "file:///splash.html",
        ] {
            assert!(!local_asset(
                &address.parse().unwrap(),
                "/splash.html",
                Some(&origin)
            ));
        }
    }

    #[test]
    fn splash_has_no_runtime_or_filesystem_plugin_capability() {
        let capability: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/splash.json")).unwrap();
        assert_eq!(capability["windows"], json!(["splash"]));
        assert_eq!(
            capability["permissions"],
            json!([
                "core:event:allow-listen",
                "core:event:allow-unlisten",
                "core:window:allow-start-dragging"
            ])
        );
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let windows = config["app"]["windows"].as_array().unwrap();
        assert_eq!(
            windows
                .iter()
                .find(|window| window["label"] == "main")
                .unwrap()["visible"],
            false
        );
        assert_eq!(
            windows
                .iter()
                .find(|window| window["label"] == "splash")
                .unwrap()["create"],
            false
        );
    }

    #[test]
    fn concurrent_second_launch_cannot_be_lost_after_ready_drains_files() {
        for _ in 0..100 {
            let latest = Arc::new(Mutex::new(SplashSnapshot::new("1.57.0".into())));
            let queue = Arc::new(Mutex::new(Vec::new()));
            let barrier = Arc::new(Barrier::new(2));
            let incoming = {
                let latest = Arc::clone(&latest);
                let queue = Arc::clone(&queue);
                let barrier = Arc::clone(&barrier);
                std::thread::spawn(move || {
                    let mut files = vec!["second-launch.dpw".into()];
                    barrier.wait();
                    let buffered = buffer_startup_files(&latest, &queue, &mut files).unwrap();
                    (buffered, files)
                })
            };
            barrier.wait();
            latest.lock().unwrap().phase = SplashPhase::Ready;
            let delivered = std::mem::take(&mut *queue.lock().unwrap());
            let (buffered, immediate) = incoming.join().unwrap();
            if buffered {
                assert_eq!(delivered, vec!["second-launch.dpw"]);
                assert!(immediate.is_empty());
            } else {
                assert!(delivered.is_empty());
                assert_eq!(immediate, vec!["second-launch.dpw"]);
            }
            assert!(queue.lock().unwrap().is_empty());
        }
    }
}
