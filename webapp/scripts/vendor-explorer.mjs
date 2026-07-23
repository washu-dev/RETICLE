/**
 * Vendoring generator: lift the standalone gene-explorer prototype
 * (prototype/web/index.html) into a webapp ES module that mounts inside a
 * Shadow DOM.
 *
 * Why a generator instead of hand-porting: the prototype UI is a single
 * 966-line file of hand-written vanilla JS + inline SVG/canvas. We want its
 * exact behavior and editorial identity preserved, and we want to be able to
 * re-vendor if the prototype changes. So we transform it mechanically:
 *
 *   - CSS goes verbatim into a Shadow DOM <style> (total isolation from the
 *     webapp's dark theme). `:root` -> `:host`; page-level `body` rules are
 *     rebound to a `.rx-body` wrapper element.
 *   - The JS runs inside mountExplorer(host, apiBase): `$`/querySelectorAll/
 *     getElementById are rebound to the shadow root, `document.body` to the
 *     wrapper, and `fetch('/api/...')` to the configured API base.
 *   - Inline onclick handlers call functions we re-expose on window while the
 *     Explorer is mounted (and remove on unmount).
 *
 * Run:  node scripts/vendor-explorer.mjs      (from webapp/)
 * Out:  src/components/explorer/vendor/explorerBundle.js
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "../../prototype/web/index.html");
const OUT_DIR = resolve(__dirname, "../src/components/explorer/vendor");
const OUT = resolve(OUT_DIR, "explorerBundle.js");

const html = readFileSync(SRC, "utf8");

// --- extract the three parts ------------------------------------------------
const css = html.match(/<style>([\s\S]*?)<\/style>/)[1];
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
// body markup = everything in <body> before <script>
const bodyInner = html.match(/<body>([\s\S]*?)<script>/)[1];

// --- CSS transforms: make it Shadow-DOM safe --------------------------------
let cssOut = css
  .replace(/:root\s*\{/, ":host{")
  .replace(/\bhtml\s*,\s*body\s*\{[^}]*\}/, "") // drop html,body margin reset
  .replace(/\nbody\s*\{/, "\n.rx-body{min-height:100vh;") // page bg -> wrapper
  .replace(/\bbody\.compact-view\b/g, ".rx-body.compact-view");

// --- markup: wrap in the .rx-body element + a "back to app" bar -------------
const backBar =
  '<div class="rx-topnav"><button class="rx-back" type="button" ' +
  'onclick="window.__rxBack&&window.__rxBack()">← Back to RETICLE app</button>' +
  '<span class="rx-topnav-tag">Gene Explorer</span></div>';
const markup = `<div class="rx-body">${backBar}${bodyInner}</div>`;

// styling for the section-boundary bar (deliberate, quiet — the signature
// stays the network/hero, per the design direction)
const navCss = `
.rx-topnav{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:14px clamp(26px,6vw,96px);border-bottom:1px solid var(--line);
  background:rgba(252,252,251,.9);backdrop-filter:blur(6px);position:sticky;top:0;z-index:40}
.rx-back{font-family:var(--mono);font-size:12px;color:var(--ess);background:#fff;
  border:1px solid var(--line);border-radius:9px;padding:7px 13px;cursor:pointer;transition:.15s}
.rx-back:hover{background:var(--ess-soft);border-color:var(--ess)}
.rx-back:focus-visible{outline:2px solid var(--ess);outline-offset:2px}
.rx-topnav-tag{font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint)}
`;

// --- JS transforms: rebind document/global refs to the shadow root ----------
let jsOut = script
  // $ and querying rebind to the shadow root (defined in preamble)
  .replace(/const\s+\$\s*=\s*s\s*=>\s*document\.querySelector\(s\);?/, "")
  .replace(/document\.querySelectorAll\(/g, "root.querySelectorAll(")
  .replace(/document\.getElementById\(/g, "root.getElementById(")
  .replace(/document\.body\.classList/g, "rxBody.classList")
  // point every API call at the configured base
  .replace(/fetch\('\/api\//g, "fetch(APIBASE+'/api/")
  .replace(/fetch\(`\/api\//g, "fetch(`${APIBASE}/api/")
  // the screen-row pivot used document.getElementById('qs') which isn't in the
  // shadow tree; drop the cosmetic search-box update, keep the pivot itself
  .replace(/document\.getElementById\('qs'\)\.value='\$\{_scrEsc\(x\.screen_id\)\}';/g, "");

// preamble/postamble that scope the vendored code and expose inline handlers
const preamble = `
  const root = host.__rxRoot || host.attachShadow({ mode: "open" });
  host.__rxRoot = root;
  const APIBASE = (apiBase || "").replace(/\\/$/, "");
  root.innerHTML = '<style>' + EXPLORER_CSS + '</style>' + EXPLORER_MARKUP;
  const rxBody = root.querySelector(".rx-body");
  const $ = (s) => root.querySelector(s);
  // ShadowRoot lacks getElementById in some engines — shim it
  if (!root.getElementById) root.getElementById = (id) => root.querySelector("#" + id);
`;
const postamble = `
  window.explore = explore;
  window.findSimilar = findSimilar;
  window.loadMoreSimilar = loadMoreSimilar;
  return function cleanup() {
    try { root.querySelectorAll("svg").forEach((s) => s._raf && cancelAnimationFrame(s._raf)); } catch (e) {}
    delete window.explore; delete window.findSimilar; delete window.loadMoreSimilar;
  };
`;

const banner =
  "// AUTO-GENERATED by scripts/vendor-explorer.mjs from prototype/web/index.html.\n" +
  "// Do not edit by hand — re-run the generator to update.\n" +
  "/* eslint-disable */\n";

const file =
  banner +
  "export const EXPLORER_CSS = " +
  JSON.stringify(cssOut + navCss) +
  ";\n\n" +
  "export const EXPLORER_MARKUP = " +
  JSON.stringify(markup) +
  ";\n\n" +
  "export function mountExplorer(host, apiBase) {\n" +
  preamble +
  "\n// ---- begin vendored prototype JS ----\n" +
  jsOut +
  "\n// ---- end vendored prototype JS ----\n" +
  postamble +
  "}\n";

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(OUT, file, "utf8");
console.log("wrote", OUT, "(" + file.length + " bytes)");
