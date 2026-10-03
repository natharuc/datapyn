import { desktopRoot, main, run } from "./common.mjs";
import { join } from "node:path";

await main(async () => {
  const cwd = join(desktopRoot, "src-tauri");
  const cargo = process.platform === "win32" ? "cargo.exe" : "cargo";
  for (const args of [["fmt", "--check"], ["check", "--locked"], ["test", "--locked"]]) {
    const code = await run(cargo, args, { cwd });
    if (code !== 0) return code;
  }
  return 0;
});
