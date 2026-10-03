import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import {fileURLToPath} from "node:url";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  input: {main:fileURLToPath(new URL("./index.html",import.meta.url)),splash:fileURLToPath(new URL("./splash.html",import.meta.url))},
  server: { port: 1420, strictPort: true, host: "127.0.0.1", watch: { ignored: ["**/src-tauri/**"] } },
  build: { target: "es2022", sourcemap: true, chunkSizeWarningLimit: 2500 },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
