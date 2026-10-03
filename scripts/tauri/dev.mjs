import { developmentEnvironment, main, run, runtimePython, tauriCli } from "./common.mjs";

await main(async () => {
  const env = developmentEnvironment();
  env.DATAPYN_RUNTIME_PYTHON = runtimePython(env);
  return run(process.execPath, [tauriCli(), "dev", ...process.argv.slice(2)], { env });
});
