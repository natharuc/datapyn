//! Native execution notifications with retained, immutable navigation targets.
//!
//! The notification plugin's desktop implementation ignores action metadata and
//! dispatches delivery errors to an unobserved task. Use Windows' WinRT API here
//! so both body clicks and button clicks reach the original execution target.

use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, VecDeque},
    sync::Mutex,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{Emitter, Manager, State};

const MAX_NOTICES: usize = 512;
const NOTICE_LIFETIME: Duration = Duration::from_secs(7 * 24 * 60 * 60);
const OPEN_ACTION: &str = "datapyn-open";
const EXECUTION_GROUP: &str = "executions";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ExecutionTarget {
    workspace_id: String,
    session_id: String,
    block_id: String,
    execution_id: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ExecutionNotification {
    title: String,
    body: String,
    sound: bool,
    target: ExecutionTarget,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(crate) struct Activation {
    notification_id: String,
    target: ExecutionTarget,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct NativeFailure {
    code: String,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    setting: Option<String>,
}

impl NativeFailure {
    pub(crate) fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            setting: None,
        }
    }

    pub(crate) fn at(code: &str, stage: &str, error: impl std::fmt::Display) -> Self {
        Self::new(code, format!("{stage}: {error}"))
    }
}

#[derive(Serialize)]
pub(crate) struct ShownNotification {
    notification_id: String,
    native: bool,
}

#[derive(Clone, Serialize)]
struct DeliveryFailure {
    notification_id: String,
    target: ExecutionTarget,
    error: NativeFailure,
}

struct IssuedNotice {
    target: ExecutionTarget,
    created: Instant,
    activated: bool,
    acknowledged: bool,
}

struct NoticeBook {
    sequence: u64,
    issued: BTreeMap<String, IssuedNotice>,
    order: VecDeque<String>,
    pending: VecDeque<Activation>,
}

impl Default for NoticeBook {
    fn default() -> Self {
        Self {
            sequence: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos() as u64,
            issued: BTreeMap::new(),
            order: VecDeque::new(),
            pending: VecDeque::new(),
        }
    }
}

impl NoticeBook {
    fn reserve(&mut self, target: ExecutionTarget, now: Instant) -> (String, Vec<String>) {
        let mut expired = Vec::new();
        while let Some(oldest) = self.order.front() {
            let stale = self.issued.get(oldest).map_or(true, |item| {
                now.saturating_duration_since(item.created) >= NOTICE_LIFETIME
            });
            if !stale && self.issued.len() < MAX_NOTICES {
                break;
            }
            let oldest = self.order.pop_front().unwrap();
            self.remove(&oldest);
            expired.push(oldest);
        }
        self.sequence = self.sequence.wrapping_add(1);
        let id = format!("{:016x}", self.sequence);
        self.issued.insert(
            id.clone(),
            IssuedNotice {
                target,
                created: now,
                activated: false,
                acknowledged: false,
            },
        );
        self.order.push_back(id.clone());
        (id, expired)
    }

    fn activate(&mut self, id: &str, now: Instant) -> Option<Activation> {
        let issued = self.issued.get_mut(id)?;
        if issued.activated
            || issued.acknowledged
            || now.saturating_duration_since(issued.created) >= NOTICE_LIFETIME
        {
            return None;
        }
        issued.activated = true;
        let activation = Activation {
            notification_id: id.into(),
            target: issued.target.clone(),
        };
        self.pending.push_back(activation.clone());
        Some(activation)
    }

    fn pending(&self, now: Instant) -> Vec<Activation> {
        self.pending
            .iter()
            .filter(|item| {
                self.issued
                    .get(&item.notification_id)
                    .is_some_and(|issued| {
                        now.saturating_duration_since(issued.created) < NOTICE_LIFETIME
                    })
            })
            .cloned()
            .collect()
    }

    fn acknowledge(&mut self, id: &str) -> bool {
        let Some(issued) = self.issued.get_mut(id) else {
            return false;
        };
        if !issued.activated || issued.acknowledged {
            return false;
        }
        issued.acknowledged = true;
        self.pending.retain(|item| item.notification_id != id);
        true
    }

    fn remove(&mut self, id: &str) {
        self.issued.remove(id);
        self.order.retain(|item| item != id);
        self.pending.retain(|item| item.notification_id != id);
    }
}

#[derive(Default)]
pub(crate) struct NativeNotifications {
    book: Mutex<NoticeBook>,
    #[cfg(windows)]
    toasts: Mutex<BTreeMap<String, RetainedToast>>,
    #[cfg(windows)]
    activator: Mutex<Option<super::notification_activator::ActivationRegistration>>,
}

impl NativeNotifications {
    pub(crate) fn initialize(&self, app: &tauri::AppHandle) {
        self.clear();
        #[cfg(windows)]
        if let Err(error) = self.ensure_activator(app) {
            eprintln!("DataPyn notification activator: {}", error.message);
        }
        #[cfg(not(windows))]
        let _ = app;
    }

    #[cfg(windows)]
    fn ensure_activator(&self, app: &tauri::AppHandle) -> Result<(), NativeFailure> {
        let mut activator = self.activator.lock().map_err(|_| {
            NativeFailure::new(
                "notification_state_unavailable",
                "Notification activator state unavailable",
            )
        })?;
        if activator.is_none() {
            let registered =
                super::notification_activator::ActivationRegistration::register(app.clone())
                    .map_err(|error| {
                        NativeFailure::at(
                            "native_activation_failed",
                            "Activator.CoRegisterClassObject",
                            error,
                        )
                    })?;
            *activator = Some(registered);
        }
        Ok(())
    }

    pub(crate) fn shutdown(&self) {
        self.clear();
        #[cfg(windows)]
        if let Ok(mut activator) = self.activator.lock() {
            let registered = activator.take();
            drop(activator);
            // Revoke outside the mutex: a final COM callback can race shutdown.
            drop(registered);
        }
    }

    pub(crate) fn clear(&self) {
        if let Ok(mut book) = self.book.lock() {
            *book = NoticeBook::default();
        }
        #[cfg(windows)]
        if let Ok(mut toasts) = self.toasts.lock() {
            let removed = std::mem::take(&mut *toasts);
            drop(toasts);
            drop(removed);
        }
        #[cfg(windows)]
        remove_windows_history(&[], true);
    }

    #[cfg(windows)]
    fn release(&self, ids: &[String]) {
        let removed = if let Ok(mut toasts) = self.toasts.lock() {
            ids.iter()
                .filter_map(|id| toasts.remove(id))
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        // Remove COM handlers outside the state mutex: a native event can race.
        drop(removed);
        remove_windows_history(ids, false);
    }
}

#[cfg(any(windows, test))]
fn cleanup_history_entries(
    ids: &[String],
    clear_group: bool,
    mut remove: impl FnMut(Option<&str>) -> Result<(), String>,
) -> Vec<String> {
    if clear_group {
        return remove(None).err().into_iter().collect();
    }
    // A missing tag or one failing Windows call must not leave later tags alive.
    ids.iter().filter_map(|id| remove(Some(id)).err()).collect()
}

#[cfg(windows)]
fn remove_windows_history(ids: &[String], clear_group: bool) {
    use windows::{core::HSTRING, UI::Notifications::ToastNotificationManager};
    if !clear_group && ids.is_empty() {
        return;
    }
    // Do not call identity::ensure: shutdown/startup cleanup must work even if
    // shortcut registration is unavailable. Never clear another app or group.
    let history = match ToastNotificationManager::History() {
        Ok(history) => history,
        Err(error) => {
            eprintln!("DataPyn notification cleanup History: {error}");
            return;
        }
    };
    let app_id = HSTRING::from(super::notification_identity::APP_ID);
    let group = HSTRING::from(EXECUTION_GROUP);
    let failures = cleanup_history_entries(ids, clear_group, |tag| {
        let (stage, result) = match tag {
            Some(tag) => (
                "RemoveGroupedTagWithId",
                history.RemoveGroupedTagWithId(&HSTRING::from(tag), &group, &app_id),
            ),
            None => (
                "RemoveGroupWithId",
                history.RemoveGroupWithId(&group, &app_id),
            ),
        };
        result.map_err(|error| format!("{stage}: {error}"))
    });
    for error in failures {
        // Cleanup errors are diagnostic only; execution and activation proceed.
        eprintln!("DataPyn notification cleanup {error}");
    }
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn valid_xml_text(value: &str) -> bool {
    value.chars().all(|character| {
        matches!(character, '\n' | '\r' | '\t')
            || (character >= ' ' && character != '\u{fffe}' && character != '\u{ffff}')
    })
}

fn validate(notification: &ExecutionNotification) -> Result<(), NativeFailure> {
    let target = &notification.target;
    if ![
        &target.workspace_id,
        &target.session_id,
        &target.block_id,
        &target.execution_id,
    ]
    .into_iter()
    .all(|value| valid_identifier(value))
    {
        return Err(NativeFailure::new("invalid_target", "Notification targets must contain valid local workspace, session, block and execution identifiers"));
    }
    if notification.title.trim().is_empty()
        || notification.title.chars().count() > 256
        || notification.body.chars().count() > 4096
        || !valid_xml_text(&notification.title)
        || !valid_xml_text(&notification.body)
    {
        return Err(NativeFailure::new(
            "invalid_notification",
            "Notification title/body is empty, too long or contains invalid characters",
        ));
    }
    Ok(())
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

fn toast_xml(notification: &ExecutionNotification, id: &str) -> String {
    let action = format!("{OPEN_ACTION}:{id}");
    format!("<toast launch=\"{action}\" duration=\"long\"><visual><binding template=\"ToastGeneric\"><text>{}</text><text>{}</text></binding></visual><actions><action content=\"Abrir resultado\" arguments=\"{action}\" activationType=\"foreground\"/></actions>{}</toast>",
        xml_escape(&notification.title), xml_escape(&notification.body),
        if notification.sound { "<audio src=\"ms-winsoundevent:Notification.Default\"/>" } else { "<audio silent=\"true\"/>" })
}

fn native_activation_id<'a>(
    expected_app_id: &str,
    app_id: &str,
    arguments: &'a str,
) -> Option<&'a str> {
    if app_id != expected_app_id {
        return None;
    }
    let id = arguments.strip_prefix(OPEN_ACTION)?.strip_prefix(':')?;
    (id.len() == 16
        && id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)))
    .then_some(id)
}

#[cfg(windows)]
pub(crate) fn route_native_activation(app: &tauri::AppHandle, app_id: &str, arguments: &str) {
    if let Some(id) = native_activation_id(super::notification_identity::APP_ID, app_id, arguments)
    {
        route_activation(app, id);
    }
}

fn restore_window(mut action: impl FnMut(&str) -> Result<(), String>) -> Vec<String> {
    ["unminimize", "show", "focus"]
        .into_iter()
        .filter_map(|step| action(step).err().map(|error| format!("{step}: {error}")))
        .collect()
}

fn route_activation(app: &tauri::AppHandle, id: &str) {
    let activation = app
        .state::<NativeNotifications>()
        .book
        .lock()
        .ok()
        .and_then(|mut book| book.activate(id, Instant::now()));
    let Some(activation) = activation else {
        return;
    };
    let handle = app.clone();
    let failed = activation.clone();
    if let Err(error) = app.run_on_main_thread(move || {
        let errors = if let Some(window) = handle.get_webview_window("main") {
            let errors = restore_window(|step| {
                match step {
                    "unminimize" => window.unminimize(),
                    "show" => window.show(),
                    _ => window.set_focus(),
                }
                .map_err(|error| error.to_string())
            });
            // The pending queue retains the target until frontend acknowledgement,
            // including a click received while React was reloading.
            let _ = window.emit("datapyn-notification-activate", &activation);
            errors
        } else {
            vec!["Main window unavailable".into()]
        };
        if !errors.is_empty() {
            let _ = handle.emit_to(
                "main",
                "datapyn-notification-error",
                DeliveryFailure {
                    notification_id: activation.notification_id,
                    target: activation.target,
                    error: NativeFailure::new("window_activation_failed", errors.join("; ")),
                },
            );
        }
    }) {
        let _ = app.emit_to(
            "main",
            "datapyn-notification-error",
            DeliveryFailure {
                notification_id: failed.notification_id,
                target: failed.target,
                error: NativeFailure::new("window_activation_failed", error.to_string()),
            },
        );
    }
}

#[cfg(windows)]
struct RetainedToast {
    toast: windows::UI::Notifications::ToastNotification,
    activated: i64,
    failed: i64,
}

#[cfg(windows)]
impl Drop for RetainedToast {
    fn drop(&mut self) {
        let _ = self.toast.RemoveActivated(self.activated);
        let _ = self.toast.RemoveFailed(self.failed);
    }
}

#[cfg(windows)]
fn check_native_setting(
    setting: windows::core::Result<windows::UI::Notifications::NotificationSetting>,
) -> Result<(), NativeFailure> {
    use windows::{core::HRESULT, UI::Notifications::NotificationSetting};
    let setting = match setting {
        Ok(setting) => setting,
        // The notification service may not have sender settings yet for a new
        // unpackaged AUMID. This is missing state, not an explicit denial. Show
        // remains authoritative and still enforces Windows policy/permissions.
        Err(error) if error.code() == HRESULT(0x80070490_u32 as i32) => return Ok(()),
        Err(error) => {
            return Err(NativeFailure::at(
                "native_delivery_failed",
                "Setting",
                error,
            ))
        }
    };
    if setting == NotificationSetting::Enabled {
        return Ok(());
    }
    let setting = match setting {
        NotificationSetting::DisabledForApplication => "disabled_for_application",
        NotificationSetting::DisabledForUser => "disabled_for_user",
        NotificationSetting::DisabledByGroupPolicy => "disabled_by_group_policy",
        NotificationSetting::DisabledByManifest => "disabled_by_manifest",
        _ => "disabled",
    };
    Err(NativeFailure {
        code: "native_notifications_disabled".into(),
        message: "Windows has disabled native notifications".into(),
        setting: Some(setting.into()),
    })
}

#[cfg(windows)]
fn show_windows(
    app: &tauri::AppHandle,
    notification: ExecutionNotification,
) -> Result<ShownNotification, NativeFailure> {
    use windows::core::Interface;
    use windows::{
        core::{IInspectable, HSTRING},
        Data::Xml::Dom::XmlDocument,
        Foundation::TypedEventHandler,
        UI::Notifications::{
            ToastActivatedEventArgs, ToastFailedEventArgs, ToastNotification,
            ToastNotificationManager,
        },
    };

    let state = app.state::<NativeNotifications>();
    state.ensure_activator(app)?;
    let app_id = super::notification_identity::ensure(app)?;
    let native_error = |stage: &str, error: windows::core::Error| {
        NativeFailure::at("native_delivery_failed", stage, error)
    };
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&HSTRING::from(app_id))
        .map_err(|error| native_error("CreateToastNotifierWithId", error))?;
    check_native_setting(notifier.Setting())?;
    let (id, expired) = state
        .book
        .lock()
        .map_err(|_| {
            NativeFailure::new(
                "notification_state_unavailable",
                "Notification state unavailable",
            )
        })?
        .reserve(notification.target.clone(), Instant::now());
    state.release(&expired);
    let result =
        (|| -> Result<ShownNotification, NativeFailure> {
            let document =
                XmlDocument::new().map_err(|error| native_error("XML.CreateDocument", error))?;
            document
                .LoadXml(&HSTRING::from(toast_xml(&notification, &id)))
                .map_err(|error| native_error("XML.LoadXml", error))?;
            let toast = ToastNotification::CreateToastNotification(&document)
                .map_err(|error| native_error("CreateToastNotification", error))?;

            toast
                .SetTag(&HSTRING::from(&id))
                .map_err(|error| native_error("SetTag", error))?;
            toast
                .SetGroup(&HSTRING::from(EXECUTION_GROUP))
                .map_err(|error| native_error("SetGroup", error))?;
            let activated_app = app.clone();
            let activated_id = id.clone();
            let activated = toast
                .Activated(&TypedEventHandler::<ToastNotification, IInspectable>::new(
                    move |_, arguments| {
                        let action = arguments
                            .as_ref()
                            .and_then(|value| value.cast::<ToastActivatedEventArgs>().ok())
                            .and_then(|value| value.Arguments().ok())
                            .map(|value| value.to_string());
                        if let Some(action) = action.as_deref() {
                            let app_id = super::notification_identity::APP_ID;
                            if native_activation_id(app_id, app_id, action)
                                == Some(activated_id.as_str())
                            {
                                route_native_activation(&activated_app, app_id, action);
                            }
                        }
                        Ok(())
                    },
                ))
                .map_err(|error| native_error("Activated.Subscribe", error))?;
            let failed_app = app.clone();
            let failed_id = id.clone();
            let target = notification.target.clone();
            let failed = match toast.Failed(&TypedEventHandler::<
                ToastNotification,
                ToastFailedEventArgs,
            >::new(move |_, arguments| {
                let message = arguments
                    .as_ref()
                    .and_then(|value| value.ErrorCode().ok())
                    .map(|code| format!("Failed.Event: Windows toast delivery failed: {code:?}"))
                    .unwrap_or_else(|| "Failed.Event: Windows toast delivery failed".into());
                if let Ok(mut book) = failed_app.state::<NativeNotifications>().book.lock() {
                    book.remove(&failed_id);
                }
                // Failed can arrive on a COM callback thread before Show returns.
                // Release on the UI queue after the retained toast is inserted.
                let cleanup_app = failed_app.clone();
                let cleanup_id = failed_id.clone();
                let _ = failed_app.run_on_main_thread(move || {
                    cleanup_app
                        .state::<NativeNotifications>()
                        .release(&[cleanup_id]);
                });
                let _ = failed_app.emit_to(
                    "main",
                    "datapyn-notification-error",
                    DeliveryFailure {
                        notification_id: failed_id.clone(),
                        target: target.clone(),
                        error: NativeFailure::new("native_delivery_failed", message),
                    },
                );
                Ok(())
            })) {
                Ok(token) => token,
                Err(error) => {
                    let _ = toast.RemoveActivated(activated);
                    state.book.lock().ok().map(|mut book| book.remove(&id));
                    return Err(native_error("Failed.Subscribe", error));
                }
            };
            let retained = RetainedToast {
                toast: toast.clone(),
                activated,
                failed,
            };
            if let Err(error) = notifier.Show(&toast) {
                state.book.lock().ok().map(|mut book| book.remove(&id));
                return Err(native_error("Show", error));
            }
            state
                .toasts
                .lock()
                .map_err(|_| {
                    NativeFailure::new(
                        "notification_state_unavailable",
                        "Notification state unavailable",
                    )
                })?
                .insert(id.clone(), retained);
            Ok(ShownNotification {
                notification_id: id.clone(),
                native: true,
            })
        })();
    if result.is_err() {
        state.book.lock().ok().map(|mut book| book.remove(&id));
        state.release(&[id]);
    }
    result
}

#[tauri::command]
pub(crate) async fn execution_notification_show(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    notification: ExecutionNotification,
) -> Result<ShownNotification, NativeFailure> {
    super::require_local_window(&window, &["main"])
        .map_err(|error| NativeFailure::new("unauthorized_window", error))?;
    validate(&notification)?;
    #[cfg(windows)]
    {
        let (sender, receiver) = tokio::sync::oneshot::channel();
        let handle = app.clone();
        app.run_on_main_thread(move || {
            let _ = sender.send(show_windows(&handle, notification));
        })
        .map_err(|error| NativeFailure::new("native_delivery_failed", error.to_string()))?;
        receiver.await.map_err(|_| {
            NativeFailure::new(
                "native_delivery_failed",
                "Native notification task was interrupted",
            )
        })?
    }
    #[cfg(not(windows))]
    {
        let _ = app;
        Err(NativeFailure::new(
            "unsupported_platform",
            "Clickable native execution notifications are currently available on Windows",
        ))
    }
}

#[tauri::command]
pub(crate) fn execution_notification_take_pending(
    window: tauri::WebviewWindow,
    state: State<'_, NativeNotifications>,
) -> Result<Vec<Activation>, NativeFailure> {
    super::require_local_window(&window, &["main"])
        .map_err(|error| NativeFailure::new("unauthorized_window", error))?;
    state
        .book
        .lock()
        .map(|book| book.pending(Instant::now()))
        .map_err(|_| {
            NativeFailure::new(
                "notification_state_unavailable",
                "Notification state unavailable",
            )
        })
}

#[tauri::command]
pub(crate) fn execution_notification_ack(
    window: tauri::WebviewWindow,
    state: State<'_, NativeNotifications>,
    notification_id: String,
) -> Result<bool, NativeFailure> {
    super::require_local_window(&window, &["main"])
        .map_err(|error| NativeFailure::new("unauthorized_window", error))?;
    let acknowledged = state
        .book
        .lock()
        .map(|mut book| book.acknowledge(&notification_id))
        .map_err(|_| {
            NativeFailure::new(
                "notification_state_unavailable",
                "Notification state unavailable",
            )
        })?;
    #[cfg(windows)]
    if acknowledged {
        state.release(&[notification_id]);
    }
    Ok(acknowledged)
}

#[tauri::command]
pub(crate) fn execution_notification_focus_window(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    label: String,
) -> Result<(), NativeFailure> {
    super::require_local_window(&window, &["main"])
        .map_err(|error| NativeFailure::new("unauthorized_window", error))?;
    if label != "main" && !super::native_popout_label(&label) {
        return Err(NativeFailure::new(
            "invalid_window",
            "Only the DataPyn main window or its panel windows can receive notification focus",
        ));
    }
    let target = app.get_webview_window(&label).ok_or_else(|| {
        NativeFailure::new(
            "window_activation_failed",
            "Notification target window is no longer available",
        )
    })?;
    if label != "main" {
        let origin = if cfg!(debug_assertions) {
            app.config().build.dev_url.as_ref()
        } else {
            None
        };
        if !target
            .url()
            .is_ok_and(|url| url.as_str() == "about:blank" || super::local_popout(&url, origin))
        {
            return Err(NativeFailure::new(
                "invalid_window",
                "Only local DataPyn panel windows can receive notification focus",
            ));
        }
    }
    let errors = restore_window(|step| {
        match step {
            "unminimize" => target.unminimize(),
            "show" => target.show(),
            _ => target.set_focus(),
        }
        .map_err(|error| error.to_string())
    });
    if errors.is_empty() {
        Ok(())
    } else {
        Err(NativeFailure::new(
            "window_activation_failed",
            errors.join("; "),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_failure_preserves_stage_and_hresult_in_serialized_message() {
        let error = NativeFailure::at(
            "native_delivery_failed",
            "Show",
            "Element not found (0x80070490)",
        );
        let value = serde_json::to_value(error).unwrap();
        assert_eq!(value["code"], "native_delivery_failed");
        assert_eq!(value["message"], "Show: Element not found (0x80070490)");
        assert!(value.get("setting").is_none());
    }

    #[cfg(windows)]
    #[test]
    fn missing_sender_setting_allows_first_show_but_denials_and_other_errors_stop_it() {
        use windows::{
            core::{Error, HRESULT},
            UI::Notifications::NotificationSetting,
        };
        assert!(check_native_setting(Ok(NotificationSetting::Enabled)).is_ok());
        assert!(
            check_native_setting(Err(Error::from_hresult(HRESULT(0x80070490_u32 as i32)))).is_ok()
        );
        for (setting, reason) in [
            (
                NotificationSetting::DisabledForApplication,
                "disabled_for_application",
            ),
            (NotificationSetting::DisabledForUser, "disabled_for_user"),
            (
                NotificationSetting::DisabledByGroupPolicy,
                "disabled_by_group_policy",
            ),
            (
                NotificationSetting::DisabledByManifest,
                "disabled_by_manifest",
            ),
            (NotificationSetting(99), "disabled"),
        ] {
            let error = check_native_setting(Ok(setting)).unwrap_err();
            assert_eq!(error.code, "native_notifications_disabled");
            assert_eq!(error.setting.as_deref(), Some(reason));
        }
        let error = check_native_setting(Err(Error::from_hresult(HRESULT(0x80070005_u32 as i32))))
            .unwrap_err();
        assert_eq!(error.code, "native_delivery_failed");
        assert!(error.message.starts_with("Setting:"));
        assert!(error.setting.is_none());
    }

    #[test]
    fn com_activation_accepts_only_exact_identity_and_bounded_opaque_notice_id() {
        let app_id = "app.datapyn.tauri";
        let id = "0123456789abcdef";
        assert_eq!(
            native_activation_id(app_id, app_id, &format!("datapyn-open:{id}")),
            Some(id)
        );
        assert!(
            native_activation_id(app_id, "other.application", &format!("datapyn-open:{id}"))
                .is_none()
        );
        for arguments in [
            "datapyn-open",
            "datapyn-open:",
            "datapyn-open:0123456789ABCDEF",
            "datapyn-open:0123456789abcdeg",
            "datapyn-open:0123456789abcdef:workspace",
            "other-action:0123456789abcdef",
            "datapyn-open:https://example.com",
            "datapyn-open:0123456789abcde",
        ] {
            assert!(
                native_activation_id(app_id, app_id, arguments).is_none(),
                "{arguments}"
            );
        }
        let now = Instant::now();
        let mut book = NoticeBook::default();
        let (issued, _) = book.reserve(target("native"), now);
        let arguments = format!("datapyn-open:{issued}");
        let parsed = native_activation_id(app_id, app_id, &arguments).unwrap();
        assert!(book.activate(parsed, now).is_some());
        assert!(book.activate(parsed, now).is_none());
        assert!(book.activate(id, now).is_none()); // valid syntax is insufficient
    }

    fn target(value: &str) -> ExecutionTarget {
        ExecutionTarget {
            workspace_id: "workspace-1".into(),
            session_id: "session-1".into(),
            block_id: value.into(),
            execution_id: format!("execution-{value}"),
        }
    }

    fn notification() -> ExecutionNotification {
        ExecutionNotification {
            title: "Executado ✓".into(),
            body: "Linha <1> & resultado \"ok\"".into(),
            sound: false,
            target: target("block-1"),
        }
    }

    #[test]
    fn rejects_external_or_malformed_targets_and_invalid_text() {
        for id in [
            "",
            "..",
            "file:///etc/passwd",
            "https://example.com",
            "session\n1",
            "<script>",
        ] {
            let mut notice = notification();
            notice.target.block_id = id.into();
            assert_eq!(validate(&notice).unwrap_err().code, "invalid_target");
        }
        let mut notice = notification();
        notice.title = "x".repeat(257);
        assert_eq!(validate(&notice).unwrap_err().code, "invalid_notification");
        notice.title = "valid".into();
        notice.body = "invalid\0body".into();
        assert_eq!(validate(&notice).unwrap_err().code, "invalid_notification");
        assert!(validate(&notification()).is_ok());
    }

    #[test]
    fn native_template_escapes_text_and_owns_sound_once() {
        let mut notice = notification();
        let xml = toast_xml(&notice, "0123456789abcdef");
        assert!(xml.contains("Linha &lt;1&gt; &amp; resultado &quot;ok&quot;"));
        assert!(xml.contains("launch=\"datapyn-open:0123456789abcdef\""));
        assert!(xml.contains("arguments=\"datapyn-open:0123456789abcdef\""));
        assert!(xml.contains("<audio silent=\"true\"/>"));
        assert!(!xml.contains("workspace-1")); // target never comes from toast arguments
        notice.sound = true;
        let xml = toast_xml(&notice, "0123456789abcdef");
        assert_eq!(xml.matches("<audio ").count(), 1);
        assert!(xml.contains("Notification.Default"));
        assert!(!xml.contains("silent="));
    }

    #[cfg(windows)]
    #[test]
    fn windows_parses_native_template_with_unicode_and_escaped_content() {
        use windows::{
            core::HSTRING,
            Data::Xml::Dom::XmlDocument,
            Win32::System::Com::{CoInitializeEx, CoUninitialize, COINIT_MULTITHREADED},
        };
        struct Apartment;
        impl Drop for Apartment {
            fn drop(&mut self) {
                unsafe {
                    CoUninitialize();
                }
            }
        }
        unsafe {
            CoInitializeEx(None, COINIT_MULTITHREADED).ok().unwrap();
        }
        let _apartment = Apartment;
        let document = XmlDocument::new().unwrap();
        document
            .LoadXml(&HSTRING::from(toast_xml(
                &notification(),
                "0123456789abcdef",
            )))
            .unwrap();
        assert_eq!(
            document
                .GetElementsByTagName(&HSTRING::from("audio"))
                .unwrap()
                .Length()
                .unwrap(),
            1
        );
        assert_eq!(
            document
                .GetElementsByTagName(&HSTRING::from("action"))
                .unwrap()
                .Length()
                .unwrap(),
            1
        );
    }

    #[test]
    fn retains_original_execution_and_buffers_click_until_acknowledgement() {
        let now = Instant::now();
        let mut book = NoticeBook::default();
        let mut original = target("block-1");
        let (first, _) = book.reserve(original.clone(), now);
        original.session_id = "different-session".into();
        let (second, _) = book.reserve(target("block-2"), now);
        let first_click = book.activate(&first, now).unwrap();
        assert_eq!(first_click.target.session_id, "session-1");
        assert_eq!(first_click.target.block_id, "block-1");
        assert!(book.activate(&first, now).is_none());
        assert_eq!(book.pending(now), vec![first_click.clone()]);
        assert_eq!(book.pending(now), vec![first_click]); // reading does not consume
        assert!(!book.acknowledge(&second)); // unclicked target cannot be acknowledged
        assert!(book.acknowledge(&first));
        assert!(!book.acknowledge(&first));
        assert!(book.pending(now).is_empty());
        assert!(book.activate(&second, now).is_some());
        assert!(book.activate("foreign-id", now).is_none());
    }

    #[test]
    fn bounds_targets_and_rejects_expired_clicks() {
        let now = Instant::now();
        let mut book = NoticeBook::default();
        let (first, _) = book.reserve(target("first"), now);
        book.activate(&first, now);
        let mut removed = Vec::new();
        for index in 0..MAX_NOTICES {
            let (_, ids) = book.reserve(target(&format!("block-{index}")), now);
            removed.extend(ids);
        }
        assert_eq!(book.issued.len(), MAX_NOTICES);
        assert!(removed.contains(&first));
        assert!(book.activate(&first, now).is_none());
        assert!(book.pending(now).is_empty());
        let (recent, _) = book.reserve(target("recent"), now);
        assert!(book.activate(&recent, now + NOTICE_LIFETIME).is_none());
    }

    #[test]
    fn failed_delivery_removes_bookkeeping_without_accumulating_history() {
        let now = Instant::now();
        let mut book = NoticeBook::default();
        let (retained, _) = book.reserve(target("retained"), now);
        for index in 0..MAX_NOTICES * 3 {
            let (failed, _) = book.reserve(target(&format!("failed-{index}")), now);
            book.remove(&failed);
        }
        assert_eq!(book.order.len(), 1);
        assert_eq!(book.issued.len(), 1);
        assert!(book.activate(&retained, now).is_some());
    }

    #[test]
    fn native_history_cleanup_removes_evicted_tags_and_continues_after_failure() {
        let now = Instant::now();
        let mut book = NoticeBook::default();
        let (expired, _) = book.reserve(target("expired"), now);
        let (retained, evicted) = book.reserve(target("retained"), now + NOTICE_LIFETIME);
        assert_eq!(evicted, [expired.clone()]);
        let mut history = BTreeMap::from([(expired.clone(), true), (retained.clone(), true)]);
        assert!(cleanup_history_entries(&evicted, false, |tag| {
            history.remove(tag.unwrap());
            Ok(())
        })
        .is_empty());
        assert!(!history.contains_key(&expired));
        assert!(history.contains_key(&retained));
        let mut calls = Vec::new();
        let errors = cleanup_history_entries(&["failed".into(), "later".into()], false, |tag| {
            let tag = tag.unwrap();
            calls.push(tag.to_string());
            if tag == "failed" {
                Err("Windows refused removal".into())
            } else {
                Ok(())
            }
        });
        assert_eq!(calls, ["failed", "later"]);
        assert_eq!(errors, ["Windows refused removal"]);
        calls.clear();
        assert!(cleanup_history_entries(&[], true, |tag| {
            assert!(tag.is_none());
            calls.push(EXECUTION_GROUP.into());
            Ok(())
        })
        .is_empty());
        assert_eq!(calls, ["executions"]);
    }

    #[test]
    fn restoration_attempts_unminimize_show_and_focus_even_after_failure() {
        let mut steps = Vec::new();
        let failures = restore_window(|step| {
            steps.push(step.to_string());
            if step == "unminimize" {
                Err("test failure".into())
            } else {
                Ok(())
            }
        });
        assert_eq!(steps, ["unminimize", "show", "focus"]);
        assert_eq!(failures, ["unminimize: test failure"]);
    }
}
