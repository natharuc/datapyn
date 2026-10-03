import { bundleRuntime, main } from "./common.mjs";

await main(() => bundleRuntime(process.argv.slice(2)));
