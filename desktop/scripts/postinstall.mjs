import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { patchGlide } from "./apply-glide-patch.mjs";
import { patchDockview } from "./apply-dockview-patch.mjs";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const glide = patchGlide(desktopRoot);
console.log(`Glide 6.0.3 native-popout patch: ${glide ? `${glide} verified files patched` : "already applied"}.`);
const docking = patchDockview(desktopRoot);
console.log(`Dockview 8.4.0 floating-pointer patch: ${docking ? `${docking} verified files patched` : "already applied"}.`);
