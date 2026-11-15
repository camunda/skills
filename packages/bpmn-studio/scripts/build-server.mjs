import { build } from "esbuild";
import fs from "node:fs";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

execFileSync(process.execPath, ["scripts/gen-lint-rules.mjs"], { stdio: "inherit" });
fs.mkdirSync("dist", { recursive: true });
fs.copyFileSync(createRequire(import.meta.url).resolve("@nanobpm/engine-wasm/readmodel/nanobpmn_engine_bg.wasm"), "dist/nanobpmn_engine_bg.wasm");

await build({
  entryPoints: ["main.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  outfile: "dist/index.js",
  // @camunda/linting & friends ship extensionless ESM that Node can't load directly,
  // so we bundle everything; the engine .wasm is copied next to the bundle. dist/ is self-contained.
  banner: {
    js: "#!/usr/bin/env node\nimport { createRequire as __bpmnCreateRequire } from 'node:module';\nconst require = __bpmnCreateRequire(import.meta.url);",
  },
  logLevel: "warning",
});
console.error("built dist/index.js");
