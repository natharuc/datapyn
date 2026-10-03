import { bundleRuntime, main, optionValue, run, tauriCli } from "./common.mjs";
import { signedConfiguration } from "./release.mjs";

await main(async () => {
  const signed = process.argv.slice(2).includes("--signed");
  const args = process.argv.slice(2).filter(value => value !== "--signed");
  const signedConfig = signed ? signedConfiguration(process.env) : undefined;
  const target = optionValue(args, "--target");
  const runtimeArgs = ["--smoke", ...(target ? ["--target", target] : [])];
  const code = await bundleRuntime(runtimeArgs);
  if (code !== 0) return code;
  return run(process.execPath, [tauriCli(), "build", "--config", "src-tauri/tauri.bundle.conf.json", ...(signedConfig ? ["--config", JSON.stringify(signedConfig)] : []), ...args]);
});
