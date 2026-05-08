#!/usr/bin/env node
/**
 * Copies PDF.js legacy ES bundles from pdfjs-dist into public/Program Files/PDF.js/.
 * That folder is gitignored; Render/CI must populate it before `next build`.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const DEST_DIR = path.join(ROOT, "public", "Program Files", "PDF.js");
const LEGACY = path.join(ROOT, "node_modules", "pdfjs-dist", "legacy", "build");

const FILES = ["pdf.mjs", "pdf.worker.mjs"];

for (const name of FILES) {
  const src = path.join(LEGACY, name);
  if (!fs.existsSync(src)) {
    console.error(
      `[copyPdfJsAssets] Missing ${src}. Run npm install in daedalOS first.`
    );
    process.exit(1);
  }
}

if (fs.existsSync(DEST_DIR)) {
  fs.rmSync(DEST_DIR, { recursive: true });
}
fs.mkdirSync(DEST_DIR, { recursive: true });

for (const name of FILES) {
  fs.copyFileSync(path.join(LEGACY, name), path.join(DEST_DIR, name));
}

const bootstrap = `import * as pdfjsLib from "./pdf.mjs";
globalThis.pdfjsLib = pdfjsLib;
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "./pdf.worker.mjs",
  import.meta.url
).href;
`;

fs.writeFileSync(path.join(DEST_DIR, "pdf-bootstrap.mjs"), bootstrap, "utf8");
console.log("[copyPdfJsAssets] Copied PDF.js into public/Program Files/PDF.js/");
