// An absent GitHub secret is exported as an empty string. Tauri treats presence
// of APPLE_CERTIFICATE as a request to import a P12, even if that string is empty.
export function pruneEmptyAppleEnvironment(env) {
  for (const key of Object.keys(env)) {
    if (key.startsWith("APPLE_") && env[key] === "") delete env[key];
  }
  return env;
}
