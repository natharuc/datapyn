use serde_json::{json, Value};

pub(crate) const CHANNEL: &str = "tauri-stable";
pub(crate) const ENDPOINT: &str =
    "https://github.com/natharuc/datapyn/releases/download/tauri-stable/latest.json";

#[cfg(windows)]
pub(crate) fn windows_installer_directory(
    executable: &std::path::Path,
) -> Option<std::ffi::OsString> {
    use std::os::windows::ffi::{OsStrExt, OsStringExt};
    use std::path::{Component, Prefix};

    let directory = executable.parent().filter(|path| path.is_absolute())?;
    let wide: Vec<u16> = directory.as_os_str().encode_wide().collect();
    let directory = match directory.components().next() {
        // current_exe is canonicalized by Tauri. NSIS expects regular drive/UNC
        // notation rather than the canonical \\?\ prefix on Windows.
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::VerbatimDisk(_) => std::ffi::OsString::from_wide(&wide[4..]),
            Prefix::VerbatimUNC(_, _) => {
                let mut normal = vec![b'\\' as u16, b'\\' as u16];
                normal.extend_from_slice(&wide[8..]);
                std::ffi::OsString::from_wide(&normal)
            }
            Prefix::Verbatim(_) | Prefix::DeviceNS(_) => return None,
            _ => directory.as_os_str().to_os_string(),
        },
        _ => return None,
    };
    // NSIS requires /D= to be the final argument, without quotes even for paths
    // with spaces. Preserve native Unicode instead of serializing through UTF-8.
    let mut argument = std::ffi::OsString::from("/D=");
    argument.push(directory);
    Some(argument)
}

pub(crate) fn update_status(config: &Value, current_version: &str) -> Value {
    let public_key = config.get("pubkey").and_then(Value::as_str).unwrap_or("");
    let endpoints = config.get("endpoints").and_then(Value::as_array);
    let signed = !public_key.trim().is_empty();
    let isolated = endpoints
        .is_some_and(|items| items.len() == 1 && items[0].as_str() == Some(ENDPOINT))
        && config
            .get("dangerousInsecureTransportProtocol")
            .and_then(Value::as_bool)
            != Some(true)
        && config
            .get("dangerousAcceptInvalidCerts")
            .and_then(Value::as_bool)
            != Some(true)
        && config
            .get("dangerousAcceptInvalidHostnames")
            .and_then(Value::as_bool)
            != Some(true);
    let available = signed && isolated;
    let reason = if !signed {
        Some("Este build não tem uma chave de atualização Tauri configurada.")
    } else if !isolated {
        Some("Este build não tem o canal exclusivo do DataPyn Tauri configurado.")
    } else {
        None
    };
    json!({
        "available": available, "current_version": current_version,
        "channel": CHANNEL, "endpoint": ENDPOINT,
        "automatic_download": available && !cfg!(debug_assertions), "reason": reason
    })
}

#[cfg(test)]
mod tests {
    use super::{update_status, CHANNEL, ENDPOINT};
    use serde_json::json;

    #[cfg(windows)]
    #[test]
    fn nsis_updates_keep_installed_and_portable_directories_with_unicode_and_spaces() {
        use std::path::Path;
        for directory in [
            r"C:\Users\user\AppData\Local\DataPyn Tauri",
            r"D:\Ferramentas\Análise SQL\DataPyn-Tauri",
        ] {
            let executable = Path::new(directory).join("datapyn-desktop.exe");
            let argument = super::windows_installer_directory(&executable).unwrap();
            assert_eq!(argument.to_string_lossy(), format!("/D={directory}"));
            assert!(!argument.to_string_lossy().contains('"'));
        }
        for (path, expected) in [
            (
                r"\\?\C:\Users\user\DataPyn Tauri\datapyn-desktop.exe",
                r"/D=C:\Users\user\DataPyn Tauri",
            ),
            (
                r"\\?\UNC\server\share\DataPyn Tauri\datapyn-desktop.exe",
                r"/D=\\server\share\DataPyn Tauri",
            ),
        ] {
            assert_eq!(
                super::windows_installer_directory(Path::new(path))
                    .unwrap()
                    .to_string_lossy(),
                expected
            );
        }
        assert!(super::windows_installer_directory(Path::new("datapyn-desktop.exe")).is_none());
    }

    #[test]
    #[ignore = "Requires an actual signed release artifact in DATAPYN_UPDATE_ARTIFACT"]
    fn verify_distribution_signature() {
        use base64::{engine::general_purpose::STANDARD, Engine};
        use minisign_verify::{PublicKey, Signature};
        let artifact =
            std::env::var("DATAPYN_UPDATE_ARTIFACT").expect("Set DATAPYN_UPDATE_ARTIFACT");
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let public = config["plugins"]["updater"]["pubkey"].as_str().unwrap();
        let key_text = String::from_utf8(STANDARD.decode(public).unwrap()).unwrap();
        let signature_file = std::fs::read_to_string(format!("{artifact}.sig")).unwrap();
        let signature_text =
            String::from_utf8(STANDARD.decode(signature_file.trim()).unwrap()).unwrap();
        let key = PublicKey::decode(&key_text).unwrap();
        let signature = Signature::decode(&signature_text).unwrap();
        let mut bytes = std::fs::read(&artifact).unwrap();
        assert!(!bytes.is_empty(), "The release artifact is empty");
        key.verify(&bytes, &signature, false)
            .expect("Release signature does not match the embedded public key");
        bytes[0] ^= 1;
        assert!(
            key.verify(&bytes, &signature, false).is_err(),
            "Tampered release artifact must be rejected"
        );
    }

    #[test]
    fn only_the_signed_isolated_feed_can_be_enabled() {
        for endpoints in [
            json!([]),
            json!([
                "http://github.com/natharuc/datapyn/releases/download/tauri-stable/latest.json"
            ]),
            json!(["https://github.com/natharuc/datapyn/releases/latest/download/latest.json"]),
            json!(["https://api.github.com/repos/natharuc/datapyn/releases/latest"]),
            json!(["https://example.com/tauri-stable/latest.json"]),
            json!([
                ENDPOINT,
                "https://github.com/natharuc/datapyn/releases/latest/download/latest.json"
            ]),
        ] {
            assert_eq!(
                update_status(&json!({"pubkey":"public", "endpoints":endpoints}), "1.0.0")
                    ["available"],
                false
            );
        }
        assert_eq!(
            update_status(&json!({"pubkey":"", "endpoints":[ENDPOINT]}), "1.0.0")["available"],
            false
        );
        let status = update_status(&json!({"pubkey":"public", "endpoints":[ENDPOINT]}), "1.0.0");
        assert_eq!(status["available"], true);
        assert_eq!(status["channel"], CHANNEL);
        assert_eq!(status["current_version"], "1.0.0");
    }

    #[test]
    fn insecure_overrides_are_not_production_channels() {
        for field in [
            "dangerousInsecureTransportProtocol",
            "dangerousAcceptInvalidCerts",
            "dangerousAcceptInvalidHostnames",
        ] {
            let mut config = json!({"pubkey":"public", "endpoints":[ENDPOINT]});
            config[field] = json!(true);
            assert_eq!(update_status(&config, "1.0.0")["available"], false);
        }
    }
}
