//! Current-user identity for the unpackaged preview executable.
//!
//! Win32 toasts require a Start Menu shortcut with System.AppUserModel.ID.
//! Registry branding alone is insufficient on some Windows installations.

use crate::{execution_notifications::NativeFailure, notification_activator::ACTIVATOR_CLSID};
use std::{mem::ManuallyDrop, os::windows::ffi::OsStringExt, path::Path};
use tauri::Manager;
use windows::{
    core::{Interface, HSTRING, PCWSTR},
    Win32::{
        Foundation::PROPERTYKEY,
        System::{
            Com::{
                CoCreateInstance, CoTaskMemFree, IPersistFile,
                StructuredStorage::{
                    InitPropVariantFromCLSID, PropVariantClear, PropVariantToGUID,
                    PropVariantToString, PROPVARIANT, PROPVARIANT_0, PROPVARIANT_0_0,
                    PROPVARIANT_0_0_0,
                },
                CLSCTX_INPROC_SERVER, STGM_READWRITE,
            },
            Registry::{
                RegCloseKey, RegCreateKeyExW, RegSetValueExW, HKEY, HKEY_CURRENT_USER,
                KEY_SET_VALUE, REG_OPTION_NON_VOLATILE, REG_SZ,
            },
            Variant::VT_LPWSTR,
        },
        UI::Shell::{
            FOLDERID_Programs, IShellLinkW, PropertiesSystem::IPropertyStore, SHChangeNotify,
            SHGetKnownFolderPath, SHStrDupW, SetCurrentProcessExplicitAppUserModelID, ShellLink,
            KF_FLAG_DEFAULT, SHCNE_CREATE, SHCNE_UPDATEITEM, SHCNF_FLUSH, SHCNF_PATHW,
        },
    },
};

pub(crate) const APP_ID: &str = "app.datapyn.desktop.preview";
const SHORTCUT_NAME: &str = "DataPyn Tauri Preview.lnk";
// PKEY_AppUserModel_ID, documented System.AppUserModel.ID property.
const APP_USER_MODEL_ID: PROPERTYKEY = PROPERTYKEY {
    fmtid: windows::core::GUID::from_u128(0x9f4c2855_9f79_4b39_a8d0_e1d42de1d5f3),
    pid: 5,
};
const TOAST_ACTIVATOR_CLSID: PROPERTYKEY = PROPERTYKEY {
    fmtid: APP_USER_MODEL_ID.fmtid,
    pid: 26,
};

fn failure(stage: &str, error: impl std::fmt::Display) -> NativeFailure {
    NativeFailure::at("native_identity_failed", stage, error)
}

fn wide_path(path: &Path) -> HSTRING {
    use std::os::windows::ffi::OsStrExt;
    HSTRING::from_wide(&path.as_os_str().encode_wide().collect::<Vec<_>>())
}

unsafe fn read_app_id(link: &IShellLinkW) -> Result<String, NativeFailure> {
    let store: IPropertyStore = link
        .cast()
        .map_err(|error| failure("Shortcut.IPropertyStore", error))?;
    let mut property = unsafe { store.GetValue(&APP_USER_MODEL_ID) }
        .map_err(|error| failure("Shortcut.GetAppUserModelID", error))?;
    let mut text = [0_u16; 129];
    let result = unsafe { PropVariantToString(&property, &mut text) };
    // GetValue allocates its own variant; always release it, including errors.
    let _ = unsafe { PropVariantClear(&mut property) };
    result.map_err(|error| failure("Shortcut.ReadAppUserModelID", error))?;
    let end = text
        .iter()
        .position(|item| *item == 0)
        .unwrap_or(text.len());
    Ok(String::from_utf16_lossy(&text[..end]))
}

fn read_activator_clsid(link: &IShellLinkW) -> Result<windows::core::GUID, NativeFailure> {
    let store: IPropertyStore = link
        .cast()
        .map_err(|error| failure("Shortcut.IPropertyStore", error))?;
    let mut property = unsafe { store.GetValue(&TOAST_ACTIVATOR_CLSID) }
        .map_err(|error| failure("Shortcut.GetActivatorCLSID", error))?;
    let result = unsafe { PropVariantToGUID(&property) };
    let _ = unsafe { PropVariantClear(&mut property) };
    result.map_err(|error| failure("Shortcut.ReadActivatorCLSID", error))
}

/// Writes only our own identity. An existing foreign shortcut is never replaced.
/// Kept independent of Tauri so actual COM persistence is covered by tests.
fn install_shortcut(path: &Path, executable: &Path) -> Result<bool, NativeFailure> {
    let existed = path.exists();
    let shortcut = wide_path(path);
    let executable_wide = wide_path(executable);
    let link: IShellLinkW = unsafe { CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER) }
        .map_err(|error| failure("Shortcut.CoCreateInstance", error))?;
    let file: IPersistFile = link
        .cast()
        .map_err(|error| failure("Shortcut.IPersistFile", error))?;
    if existed {
        unsafe { file.Load(&shortcut, STGM_READWRITE) }
            .map_err(|error| failure("Shortcut.Load", error))?;
        if unsafe { read_app_id(&link) }? != APP_ID {
            return Err(failure(
                "Shortcut.IdentityConflict",
                "Existing shortcut belongs to another application",
            ));
        }
        let mut target = [0_u16; 32768];
        unsafe { link.GetPath(&mut target, std::ptr::null_mut(), 0) }
            .map_err(|error| failure("Shortcut.GetPath", error))?;
        let end = target
            .iter()
            .position(|item| *item == 0)
            .unwrap_or(target.len());
        let target = std::path::PathBuf::from(std::ffi::OsString::from_wide(&target[..end]));
        if target == executable && read_activator_clsid(&link).ok() == Some(ACTIVATOR_CLSID) {
            return Ok(false);
        }
    }
    unsafe {
        link.SetPath(&executable_wide)
            .map_err(|error| failure("Shortcut.SetPath", error))?;
        link.SetArguments(&HSTRING::new())
            .map_err(|error| failure("Shortcut.SetArguments", error))?;
        link.SetDescription(&HSTRING::from("DataPyn execution notifications"))
            .map_err(|error| failure("Shortcut.SetDescription", error))?;
        if let Some(directory) = executable.parent() {
            link.SetWorkingDirectory(&wide_path(directory))
                .map_err(|error| failure("Shortcut.SetWorkingDirectory", error))?;
        }
        link.SetIconLocation(&executable_wide, 0)
            .map_err(|error| failure("Shortcut.SetIconLocation", error))?;
    }
    set_app_id(&link, APP_ID)?;
    set_activator_clsid(&link)?;
    unsafe {
        file.Save(&shortcut, true)
            .map_err(|error| failure("Shortcut.Save", error))?;
    }
    Ok(true)
}

fn set_activator_clsid(link: &IShellLinkW) -> Result<(), NativeFailure> {
    let store: IPropertyStore = link
        .cast()
        .map_err(|error| failure("Shortcut.IPropertyStore", error))?;
    let mut property = unsafe { InitPropVariantFromCLSID(&ACTIVATOR_CLSID) }
        .map_err(|error| failure("Shortcut.AllocateActivatorCLSID", error))?;
    let result = unsafe {
        store
            .SetValue(&TOAST_ACTIVATOR_CLSID, &property)
            .map_err(|error| failure("Shortcut.SetActivatorCLSID", error))
            .and_then(|_| {
                store
                    .Commit()
                    .map_err(|error| failure("Shortcut.Commit", error))
            })
    };
    let _ = unsafe { PropVariantClear(&mut property) };
    result
}

fn local_server_command(executable: &Path) -> Result<String, NativeFailure> {
    if !executable.is_absolute() || executable.as_os_str().is_empty() {
        return Err(failure(
            "Identity.COM.ExecutablePath",
            "COM executable path must be absolute",
        ));
    }
    let executable = executable.to_string_lossy();
    if executable.contains(['"', '\0']) {
        return Err(failure(
            "Identity.COM.ExecutablePath",
            "Invalid COM executable path",
        ));
    }
    Ok(format!("\"{executable}\" -Embedding"))
}

fn register_com_server(executable: &Path) -> Result<(), NativeFailure> {
    let command = local_server_command(executable)?;
    let path = HSTRING::from(format!(
        "Software\\Classes\\CLSID\\{{{ACTIVATOR_CLSID:?}}}\\LocalServer32"
    ));
    let mut key = HKEY::default();
    unsafe {
        RegCreateKeyExW(
            HKEY_CURRENT_USER,
            &path,
            None,
            PCWSTR::null(),
            REG_OPTION_NON_VOLATILE,
            KEY_SET_VALUE,
            None,
            &mut key,
            None,
        )
        .ok()
        .map_err(|error| failure("Identity.COM.CreateLocalServer32", error))?;
    }
    let bytes: Vec<u8> = command
        .encode_utf16()
        .chain(std::iter::once(0))
        .flat_map(u16::to_le_bytes)
        .collect();
    let result = unsafe { RegSetValueExW(key, PCWSTR::null(), None, REG_SZ, Some(&bytes)) }
        .ok()
        .map_err(|error| failure("Identity.COM.SetLocalServer32", error));
    unsafe {
        let _ = RegCloseKey(key);
    }
    result
}

fn set_app_id(link: &IShellLinkW, value: &str) -> Result<(), NativeFailure> {
    let store: IPropertyStore = link
        .cast()
        .map_err(|error| failure("Shortcut.IPropertyStore", error))?;
    let app_id = unsafe { SHStrDupW(&HSTRING::from(value)) }
        .map_err(|error| failure("Shortcut.AllocateAppUserModelID", error))?;
    // Match InitPropVariantFromString: VT_LPWSTR allocated by SHStrDupW.
    // COM owns allocator semantics; PropVariantClear releases our copy.
    let mut property = PROPVARIANT {
        Anonymous: PROPVARIANT_0 {
            Anonymous: ManuallyDrop::new(PROPVARIANT_0_0 {
                vt: VT_LPWSTR,
                Anonymous: PROPVARIANT_0_0_0 { pwszVal: app_id },
                ..Default::default()
            }),
        },
    };
    let result = unsafe {
        store
            .SetValue(&APP_USER_MODEL_ID, &property)
            .map_err(|error| failure("Shortcut.SetAppUserModelID", error))
            .and_then(|_| {
                store
                    .Commit()
                    .map_err(|error| failure("Shortcut.Commit", error))
            })
    };
    let _ = unsafe { PropVariantClear(&mut property) };
    result
}

pub(crate) fn ensure(app: &tauri::AppHandle) -> Result<String, NativeFailure> {
    if app.config().identifier != APP_ID {
        return Err(failure(
            "Identity.Validate",
            "Registration is restricted to the DataPyn preview identifier",
        ));
    }
    let identity_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| failure("Identity.LocalDataPath", error))?
        .join("notifications");
    std::fs::create_dir_all(&identity_dir)
        .map_err(|error| failure("Identity.CreateDirectory", error))?;
    let icon_path = identity_dir.join("datapyn.png");
    const ICON: &[u8] = include_bytes!("../icons/256x256.png");
    if std::fs::read(&icon_path).ok().as_deref() != Some(ICON) {
        std::fs::write(&icon_path, ICON).map_err(|error| failure("Identity.WriteIcon", error))?;
    }
    let key_path = HSTRING::from(format!("Software\\Classes\\AppUserModelId\\{APP_ID}"));
    let mut key = HKEY::default();
    unsafe {
        RegCreateKeyExW(
            HKEY_CURRENT_USER,
            &key_path,
            None,
            PCWSTR::null(),
            REG_OPTION_NON_VOLATILE,
            KEY_SET_VALUE,
            None,
            &mut key,
            None,
        )
        .ok()
        .map_err(|error| failure("Identity.Registry.Create", error))?;
    }
    let result = (|| -> Result<(), NativeFailure> {
        for (name, value) in [
            ("DisplayName", "DataPyn".into()),
            ("IconUri", icon_path.to_string_lossy().into_owned()),
            ("IconBackgroundColor", "0".into()),
            ("CustomActivator", format!("{{{ACTIVATOR_CLSID:?}}}")),
        ] {
            let bytes: Vec<u8> = value
                .encode_utf16()
                .chain(std::iter::once(0))
                .flat_map(u16::to_le_bytes)
                .collect();
            unsafe { RegSetValueExW(key, &HSTRING::from(name), None, REG_SZ, Some(&bytes)) }
                .ok()
                .map_err(|error| failure(&format!("Identity.Registry.{name}"), error))?;
        }
        Ok(())
    })();
    unsafe {
        let _ = RegCloseKey(key);
    }
    result?;
    let folder = unsafe { SHGetKnownFolderPath(&FOLDERID_Programs, KF_FLAG_DEFAULT, None) }
        .map_err(|error| failure("Shortcut.ProgramsPath", error))?;
    let folder_text = unsafe { folder.to_string() };
    unsafe {
        CoTaskMemFree(Some(folder.0 as *const _));
    }
    let folder = std::path::PathBuf::from(
        folder_text.map_err(|error| failure("Shortcut.ProgramsPath", error))?,
    );
    let shortcut = folder.join(SHORTCUT_NAME);
    let existed = shortcut.exists();
    let executable =
        std::env::current_exe().map_err(|error| failure("Shortcut.ExecutablePath", error))?;
    register_com_server(&executable)?;
    if install_shortcut(&shortcut, &executable)? {
        let path = wide_path(&shortcut);
        // Publish the shortcut/property change before asking the notification
        // service to resolve our AUMID. FLUSH waits for affected Shell clients.
        unsafe {
            SHChangeNotify(
                if existed {
                    SHCNE_UPDATEITEM
                } else {
                    SHCNE_CREATE
                },
                SHCNF_PATHW | SHCNF_FLUSH,
                Some(path.as_ptr() as *const _),
                None,
            );
        }
    }
    unsafe { SetCurrentProcessExplicitAppUserModelID(&HSTRING::from(APP_ID)) }
        .map_err(|error| failure("Identity.SetProcessAppUserModelID", error))?;
    Ok(APP_ID.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::System::Com::{CoInitializeEx, CoUninitialize, COINIT_APARTMENTTHREADED};

    #[test]
    fn shortcut_persists_app_id_and_updates_only_own_executable() {
        unsafe {
            CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok().unwrap();
        }
        struct Apartment;
        impl Drop for Apartment {
            fn drop(&mut self) {
                unsafe {
                    CoUninitialize();
                }
            }
        }
        let _apartment = Apartment;
        let directory = std::env::temp_dir().join(format!(
            "datapyn-shortcut-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&directory).unwrap();
        struct Cleanup(std::path::PathBuf);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let _cleanup = Cleanup(directory.clone());
        let shortcut = directory.join("DataPyn.lnk");
        let executable = std::env::current_exe().unwrap();
        assert!(install_shortcut(&shortcut, &executable).unwrap());
        assert!(!install_shortcut(&shortcut, &executable).unwrap());
        let link: IShellLinkW =
            unsafe { CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).unwrap() };
        let file: IPersistFile = link.cast().unwrap();
        unsafe {
            file.Load(&wide_path(&shortcut), STGM_READWRITE).unwrap();
        }
        assert_eq!(unsafe { read_app_id(&link).unwrap() }, APP_ID);
        assert_eq!(read_activator_clsid(&link).unwrap(), ACTIVATOR_CLSID);
        let moved_executable = directory.join("datapyn-portable.exe");
        std::fs::copy(&executable, &moved_executable).unwrap();
        assert!(install_shortcut(&shortcut, &moved_executable).unwrap());
        assert!(!install_shortcut(&shortcut, &moved_executable).unwrap());
        // A corrupt/unrelated preexisting file cannot be silently overwritten.
        let unrelated = directory.join("foreign.lnk");
        std::fs::write(&unrelated, "foreign content").unwrap();
        let error = install_shortcut(&unrelated, &executable).unwrap_err();
        assert!(serde_json::to_value(error).unwrap()["message"]
            .as_str()
            .unwrap()
            .starts_with("Shortcut.Load:"));
        assert_eq!(
            std::fs::read_to_string(&unrelated).unwrap(),
            "foreign content"
        );
        // A valid link carrying someone else's AppUserModelID is also protected.
        unsafe {
            file.Load(&wide_path(&shortcut), STGM_READWRITE).unwrap();
        }
        set_app_id(&link, "another.application").unwrap();
        unsafe {
            file.Save(&wide_path(&shortcut), true).unwrap();
        }
        let previous = std::fs::read(&shortcut).unwrap();
        let error = install_shortcut(&shortcut, &executable).unwrap_err();
        assert!(serde_json::to_value(error).unwrap()["message"]
            .as_str()
            .unwrap()
            .starts_with("Shortcut.IdentityConflict:"));
        assert_eq!(std::fs::read(&shortcut).unwrap(), previous);
    }

    #[test]
    fn com_server_command_quotes_only_the_current_executable_path() {
        let path = Path::new(r"C:\Program Files\DataPyn Preview\datapyn-desktop.exe");
        assert_eq!(
            local_server_command(path).unwrap(),
            r#""C:\Program Files\DataPyn Preview\datapyn-desktop.exe" -Embedding"#
        );
        assert!(local_server_command(Path::new("relative.exe")).is_err());
        assert!(local_server_command(Path::new("C:\\invalid\" --eval something.exe")).is_err());
    }
}
