import { bundleRuntime, main, optionValue, run, tauriCli } from "./common.mjs";

await main(async () => {
  const args = process.argv.slice(2);
  const target = optionValue(args, "--target");
  const runtimeArgs = ["--smoke", ...(target ? ["--target", target] : [])];
  const code = await bundleRuntime(runtimeArgs);
  if (code !== 0) return code;
  return run(process.execPath, [tauriCli(), "build", "--config", "src-tauri/tauri.bundle.conf.json", ...args]);
});
