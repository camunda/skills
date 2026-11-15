import { build } from "esbuild";
import fs from "node:fs";

const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
fs.mkdirSync("dist", { recursive: true });

await build({
  entryPoints: ["src/index.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  outfile: "dist/index.js",
  define: { __VERSION__: JSON.stringify(pkg.version) },
  // Everything is bundled so dist/ runs on its own (npx and the .mcpb need no install step).
  banner: {
    js: "#!/usr/bin/env node\nimport { createRequire as __c8CreateRequire } from 'node:module';\nconst require = __c8CreateRequire(import.meta.url);",
  },
  logLevel: "warning",
});
fs.chmodSync("dist/index.js", 0o755);
console.error("built dist/index.js");
