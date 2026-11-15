import { defineConfig, type Plugin } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

/**
 * Inline the nanobpmn engine's .wasm as base64 (`virtual:engine-wasm`) and stop the
 * wasm-bindgen glue from pulling in its default `new URL(..wasm, import.meta.url)`
 * asset — the view initialises synchronously from the inlined bytes, so the host
 * iframe needs no network access at all.
 */
function engineWasm(): Plugin {
  const id = "virtual:engine-wasm";
  return {
    name: "engine-wasm-inline",
    resolveId: (s) => (s === id ? "\0" + id : null),
    load(s) {
      if (s !== "\0" + id) return null;
      const wasm = fs.readFileSync(require.resolve("@nanobpm/engine-wasm/lean/nanobpmn_engine_bg.wasm"));
      return `export default ${JSON.stringify(wasm.toString("base64"))};`;
    },
    transform(code, file) {
      if (!file.includes("nanobpmn_engine.js")) return null;
      return code.replace(/new URL\(['"]nanobpmn_engine_bg\.wasm['"],\s*import\.meta\.url\)/g, "undefined");
    },
  };
}

const INPUT = process.env.INPUT ?? "mcp-app.html";
const dev = process.env.NODE_ENV === "development";

export default defineConfig({
  plugins: [engineWasm(), viteSingleFile()],
  build: {
    sourcemap: dev ? "inline" : undefined,
    minify: !dev,
    cssMinify: !dev,
    rollupOptions: { input: INPUT },
    outDir: "dist",
    emptyOutDir: false,
    chunkSizeWarningLimit: 10000,
  },
});
