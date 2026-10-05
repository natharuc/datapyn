import { bundleRuntime, main, optionValue, run, tauriCli } from "./common.mjs";
import { signedConfiguration } from "./release.mjs";
import { prepareWindowsPrerequisites } from "./windows-prerequisites.mjs";
import { pruneEmptyAppleEnvironment } from "./build-environment.mjs";

await main(async () => {
  pruneEmptyAppleEnvironment(process.env);
  const signed = process.argv.slice(2).includes("--signed");
  const args = process.argv.slice(2).filter(value => value !== "--signed");
  const signedConfig = signed ? signedConfiguration(process.env) : undefined;
  const target = optionValue(args, "--target");
  await prepareWindowsPrerequisites(args);
  const runtimeArgs = ["--smoke", ...(target ? ["--target", target] : [])];
  const code = await bundleRuntime(runtimeArgs);
  if (code !== 0) return code;
  return run(process.execPath, [tauriCli(), "build", "--config", "src-tauri/tauri.bundle.conf.json", ...(signedConfig ? ["--config", JSON.stringify(signedConfig)] : []), ...args]);
});
