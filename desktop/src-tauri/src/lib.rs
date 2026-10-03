mod runtime;

use serde_json::Value;
use tauri::{Manager, State};

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
        .plugin(tauri_plugin_dialog::init())
        .manage(runtime::Backend::default())
        .invoke_handler(tauri::generate_handler![backend_request])
        .build(tauri::generate_context!())
        .expect("Unable to initialize the DataPyn desktop host");

    app.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            app.state::<runtime::Backend>().shutdown();
        }
    });
}
