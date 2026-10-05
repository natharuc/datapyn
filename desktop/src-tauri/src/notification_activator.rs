//! Windows toast activation through the desktop COM contract.
//!
//! The shell passes only an opaque notice ID. Navigation and identity validation
//! stay in the notification book; this server never evaluates arguments or user
//! input. Register and revoke on the application's COM-initialized UI apartment.

use std::{ffi::c_void, panic::AssertUnwindSafe, sync::Arc};
use windows::{
    core::{implement, Error, IUnknown, Interface, Ref, Result, BOOL, GUID, PCWSTR},
    Win32::{
        Foundation::{CLASS_E_NOAGGREGATION, E_INVALIDARG, E_POINTER, E_UNEXPECTED},
        System::Com::{
            CoRegisterClassObject, CoRevokeClassObject, IClassFactory, IClassFactory_Impl,
            CLSCTX_LOCAL_SERVER, REGCLS_MULTIPLEUSE,
        },
        UI::Notifications::{
            INotificationActivationCallback, INotificationActivationCallback_Impl,
            NOTIFICATION_USER_INPUT_DATA,
        },
    },
};

/// Unique to the DataPyn Tauri application, shared with shortcut/registry.
pub(crate) const ACTIVATOR_CLSID: GUID = GUID::from_u128(0x4c4c25cd_7f33_4ea0_a85e_7aa2dd71178c);

type ActivationRouter = Arc<dyn Fn(&str, &str) + Send + Sync>;

#[implement(INotificationActivationCallback)]
struct NotificationActivator {
    route: ActivationRouter,
}

impl INotificationActivationCallback_Impl for NotificationActivator_Impl {
    fn Activate(
        &self,
        appusermodelid: &PCWSTR,
        invokedargs: &PCWSTR,
        _data: *const NOTIFICATION_USER_INPUT_DATA,
        _count: u32,
    ) -> Result<()> {
        // COM supplies valid NUL-terminated strings. Bound the reads and owned
        // allocations even when another local client passes oversized arguments.
        let app_id = unsafe { bounded_text(*appusermodelid, 128)? };
        let arguments = unsafe { bounded_text(*invokedargs, 64)? };
        std::panic::catch_unwind(AssertUnwindSafe(|| (self.route)(&app_id, &arguments)))
            .map_err(|_| Error::from_hresult(E_UNEXPECTED))?;
        Ok(())
    }
}

/// The pointers must be valid COM strings through their terminator. Length is
/// checked before allocating; malformed UTF-16 cannot change the routing key.
unsafe fn bounded_text(value: PCWSTR, maximum: usize) -> Result<String> {
    if value.is_null() {
        return Err(Error::from_hresult(E_POINTER));
    }
    for length in 0..=maximum {
        if unsafe { *value.as_ptr().add(length) } == 0 {
            let text = unsafe { std::slice::from_raw_parts(value.as_ptr(), length) };
            return String::from_utf16(text).map_err(|_| Error::from_hresult(E_INVALIDARG));
        }
    }
    Err(Error::from_hresult(E_INVALIDARG))
}

#[implement(IClassFactory)]
struct ActivationFactory {
    route: ActivationRouter,
}

impl IClassFactory_Impl for ActivationFactory_Impl {
    fn CreateInstance(
        &self,
        outer: Ref<'_, IUnknown>,
        iid: *const GUID,
        result: *mut *mut c_void,
    ) -> Result<()> {
        if result.is_null() {
            return Err(Error::from_hresult(E_POINTER));
        }
        unsafe { *result = std::ptr::null_mut() };
        if !outer.is_null() {
            return Err(Error::from_hresult(CLASS_E_NOAGGREGATION));
        }
        if iid.is_null() {
            return Err(Error::from_hresult(E_POINTER));
        }
        let callback: INotificationActivationCallback = NotificationActivator {
            route: self.route.clone(),
        }
        .into();
        // QueryInterface transfers its own AddRef to the caller. Dropping our
        // temporary interface therefore leaves exactly the caller's ownership.
        unsafe { callback.query(iid, result).ok() }
    }

    fn LockServer(&self, _lock: BOOL) -> Result<()> {
        // This UI application owns server lifetime until explicit shutdown;
        // client lock/unlock calls never quit the running DataPyn application.
        Ok(())
    }
}

/// COM itself retains the registered factory. Keeping only the cookie lets the
/// application store this handle without moving apartment-bound COM interfaces.
pub(crate) struct ActivationRegistration {
    cookie: u32,
}

impl ActivationRegistration {
    pub(crate) fn register(app: tauri::AppHandle) -> Result<Self> {
        let route: ActivationRouter = Arc::new(move |app_id, arguments| {
            crate::execution_notifications::route_native_activation(&app, app_id, arguments);
        });
        let factory: IClassFactory = ActivationFactory { route }.into();
        let cookie = unsafe {
            CoRegisterClassObject(
                &ACTIVATOR_CLSID,
                &factory,
                CLSCTX_LOCAL_SERVER,
                REGCLS_MULTIPLEUSE,
            )?
        };
        Ok(Self { cookie })
    }
}

impl Drop for ActivationRegistration {
    fn drop(&mut self) {
        // Shutdown revokes on the same UI apartment before COM uninitializes.
        let _ = unsafe { CoRevokeClassObject(self.cookie) };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use windows::{core::HSTRING, Win32::Foundation::E_NOINTERFACE};

    fn factory(route: ActivationRouter) -> IClassFactory {
        ActivationFactory { route }.into()
    }

    #[test]
    fn real_factory_creates_the_callback_interface_and_routes_only_two_strings() {
        let captured = Arc::new(Mutex::new(Vec::new()));
        let output = captured.clone();
        let factory = factory(Arc::new(move |app, args| {
            output
                .lock()
                .unwrap()
                .push((app.to_owned(), args.to_owned()));
        }));
        let callback: INotificationActivationCallback =
            unsafe { factory.CreateInstance(None).unwrap() };
        let app = HSTRING::from("app.datapyn.tauri");
        let arguments = HSTRING::from("datapyn-open:0123456789abcdef");
        let unused_input = NOTIFICATION_USER_INPUT_DATA {
            Key: PCWSTR::null(),
            Value: PCWSTR::null(),
        };
        unsafe {
            callback
                .Activate(&app, &arguments, &[unused_input])
                .unwrap()
        };
        assert_eq!(
            *captured.lock().unwrap(),
            [(
                "app.datapyn.tauri".into(),
                "datapyn-open:0123456789abcdef".into()
            )]
        );
        let unknown: IUnknown = callback.cast().unwrap();
        assert!(unknown.cast::<INotificationActivationCallback>().is_ok());
    }

    #[test]
    fn factory_rejects_aggregation_and_unsupported_interfaces() {
        let factory = factory(Arc::new(|_, _| {}));
        let outer: IUnknown = factory.cast().unwrap();
        let result: Result<INotificationActivationCallback> =
            unsafe { factory.CreateInstance(Some(&outer)) };
        assert_eq!(result.unwrap_err().code(), CLASS_E_NOAGGREGATION);
        let result: Result<IClassFactory> = unsafe { factory.CreateInstance(None) };
        assert_eq!(result.unwrap_err().code(), E_NOINTERFACE);
        unsafe {
            factory.LockServer(true).unwrap();
            factory.LockServer(false).unwrap();
        }
    }

    #[test]
    fn factory_null_pointer_errors_never_return_an_uninitialized_interface() {
        let factory = factory(Arc::new(|_, _| {}));
        let call = factory.vtable().CreateInstance;
        let mut result = std::ptr::NonNull::<c_void>::dangling().as_ptr();
        let error = unsafe {
            call(
                factory.as_raw(),
                std::ptr::null_mut(),
                std::ptr::null(),
                &mut result,
            )
        };
        assert_eq!(error, E_POINTER);
        assert!(result.is_null());
        let error = unsafe {
            call(
                factory.as_raw(),
                std::ptr::null_mut(),
                &INotificationActivationCallback::IID,
                std::ptr::null_mut(),
            )
        };
        assert_eq!(error, E_POINTER);
    }

    #[test]
    fn malformed_or_oversized_com_strings_do_not_reach_the_router() {
        let captured = Arc::new(Mutex::new(0));
        let count = captured.clone();
        let callback: INotificationActivationCallback = NotificationActivator {
            route: Arc::new(move |_, _| *count.lock().unwrap() += 1),
        }
        .into();
        let valid_app = HSTRING::from("app.datapyn.tauri");
        let valid_args = HSTRING::from("datapyn-open:0123456789abcdef");
        let error = unsafe { callback.Activate(PCWSTR::null(), &valid_args, &[]) }.unwrap_err();
        assert_eq!(error.code(), E_POINTER);
        let error = unsafe { callback.Activate(&valid_app, &HSTRING::from("x".repeat(65)), &[]) }
            .unwrap_err();
        assert_eq!(error.code(), E_INVALIDARG);
        let invalid_utf16 = [0xd800, 0];
        let error =
            unsafe { callback.Activate(&valid_app, PCWSTR::from_raw(invalid_utf16.as_ptr()), &[]) }
                .unwrap_err();
        assert_eq!(error.code(), E_INVALIDARG);
        assert_eq!(*captured.lock().unwrap(), 0);
    }

    #[test]
    fn callback_panics_are_converted_to_hresult_instead_of_crossing_the_com_abi() {
        let callback: INotificationActivationCallback = NotificationActivator {
            route: Arc::new(|_, _| panic!("callback failure")),
        }
        .into();
        let error = unsafe {
            callback.Activate(
                &HSTRING::from("app.datapyn.tauri"),
                &HSTRING::from("datapyn-open:0123456789abcdef"),
                &[],
            )
        }
        .unwrap_err();
        assert_eq!(error.code(), E_UNEXPECTED);
    }

    #[test]
    fn registration_handle_is_send_and_sync_without_raw_interface_ownership() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<ActivationRegistration>();
    }
}
