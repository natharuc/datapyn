import {initializeStartup,publishStartup,startupFailed} from "./startupBridge";

// Keep this entry small: report loading failures even if the main bundle cannot load.
window.addEventListener("vite:preloadError",startupFailed);
async function boot(){
  await initializeStartup();
  await publishStartup("frontend");
  await import("./main");
}
void boot().catch(startupFailed);
