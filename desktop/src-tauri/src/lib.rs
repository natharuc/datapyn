mod runtime;

use serde_json::Value;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Mutex,
    },
};
use tauri::{Emitter, Manager, State};

#[derive(Default)]
struct StartupFiles(Mutex<Vec<String>>);

fn local_popout(url: &tauri::Url, development_origin: Option<&tauri::Url>) -> bool {
    if url.path() != "/popout.html" || !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    let asset = (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
        || (matches!(url.scheme(), "http" | "https")
            && url.host_str() == Some("tauri.localhost")
            && url.port().is_none());
    asset || development_origin.is_some_and(|origin| origin.origin() == url.origin())
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

#[tauri::command]
fn startup_files(state: State<'_, StartupFiles>) -> Result<Vec<String>, String> {
    let mut paths = state.0.lock().map_err(|_| "Startup files unavailable")?;
    Ok(std::mem::take(&mut *paths))
}

fn update_status(config: &Value, current_version: &str) -> Value {
    let public_key = config.get("pubkey").and_then(Value::as_str).unwrap_or("");
    let endpoints = config.get("endpoints").and_then(Value::as_array);
    let available = !public_key.trim().is_empty()
        && endpoints.is_some_and(|items| {
            !items.is_empty()
                && items.iter().all(|value| {
                    value
                        .as_str()
                        .and_then(|url| url.parse::<tauri::Url>().ok())
                        .is_some_and(|url| {
                            url.scheme() == "https"
                                && url.host_str().is_some()
                                && url.username().is_empty()
                                && url.password().is_none()
                        })
                })
        });
    serde_json::json!({"available": available, "current_version": current_version,
        "channel": "tauri-preview", "reason": if available {None} else {Some("Este build não tem um canal Tauri assinado configurado.")} })
}

#[tauri::command]
fn updater_status(app: tauri::AppHandle) -> Value {
    update_status(
        app.config()
            .plugins
            .0
            .get("updater")
            .unwrap_or(&Value::Null),
        &app.package_info().version.to_string(),
    )
}

#[tauri::command]
async fn backend_request(
    app: tauri::AppHandle,
    state: State<'_, runtime::Backend>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    state
        .request(app, method, params.unwrap_or_else(|| serde_json::json!({})))
        .await
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, cwd| {
            let files = collect_files(&args, &cwd);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
            let _ = app.emit("datapyn-open-files", files);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(StartupFiles(Mutex::new(collect_files(
            &std::env::args().collect::<Vec<_>>(),
            &std::env::current_dir()
                .unwrap_or_default()
                .to_string_lossy(),
        ))))
        .manage(runtime::Backend::default())
        .setup(|app| {
            let handle = app.handle().clone();
            let origin = if cfg!(debug_assertions) {
                app.config().build.dev_url.clone()
            } else {
                None
            };
            let windows = AtomicUsize::new(0);
            let config = app
                .config()
                .app
                .windows
                .iter()
                .find(|config| config.label == "main")
                .ok_or("Main window configuration is unavailable")?;
            tauri::WebviewWindowBuilder::from_config(app, config)?
                .on_new_window(move |url, features| {
                    if !local_popout(&url, origin.as_ref()) {
                        return tauri::webview::NewWindowResponse::Deny;
                    }
                    let label = format!("dock-popout-{}", windows.fetch_add(1, Ordering::Relaxed));
                    match tauri::WebviewWindowBuilder::new(
                        &handle,
                        label,
                        tauri::WebviewUrl::External("about:blank".parse().unwrap()),
                    )
                    .window_features(features)
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
                        Ok(window) => tauri::webview::NewWindowResponse::Create { window },
                        Err(error) => {
                            let _ = handle.emit("datapyn-popout-error", error.to_string());
                            tauri::webview::NewWindowResponse::Deny
                        }
                    }
                })
                .build()?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_request,
            startup_files,
            updater_status
        ])
        .build(tauri::generate_context!())
        .expect("Unable to initialize the DataPyn desktop host");

    app.run(|app, event| {
        if matches!(&event, tauri::RunEvent::WindowEvent {label,event:tauri::WindowEvent::Destroyed,..} if label == "main") {
            for (label, window) in app.webview_windows() {
                if label.starts_with("dock-popout-") { let _ = window.destroy(); }
            }
        }
        if matches!(event, tauri::RunEvent::Exit) {
            app.state::<runtime::Backend>().shutdown();
        }
    });
}

#[cfg(test)]
mod update_tests {
    use super::{local_popout, update_status};
    use serde_json::json;

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
            &json!({"pubkey":"public","endpoints":["https://example.com/tauri-preview/latest.json"]}),
            "1.57.0",
        );
        assert_eq!(status["available"], true);
        assert_eq!(status["channel"], "tauri-preview");
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
}
