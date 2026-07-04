// Verify the EXACT diagram strings embedded in lessons_deck.html parse cleanly
// (this tests what the browser actually hands mermaid.render(), not the JSON
// sources — the capstone deck's 2026-06-08 lesson: the embedding can mangle
// what the sources got right).
//
// Borrows the capstone deck's installed Node toolchain — no new dependencies:
//   docs/security/capstone_2026-06/_validate/node_modules  (jsdom + mermaid 11)
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";

// node_modules is gitignored, so a worktree's capstone copy is empty — fall
// back to the main checkout's installed toolchain (read-only borrow).
const CANDIDATES = [
  new URL("../../security/capstone_2026-06/_validate/", import.meta.url),
  new URL("file:///C:/Users/mrbla/BlarAI/docs/security/capstone_2026-06/_validate/"),
];
const VAL = CANDIDATES.find((c) => existsSync(new URL("node_modules/", c)));
if (!VAL) {
  console.log("capstone _validate/node_modules not found — toolchain unavailable");
  process.exit(1);
}
const require = createRequire(VAL);
const { JSDOM } = require("jsdom");

const dom = new JSDOM("<!DOCTYPE html><body></body>");
global.window = dom.window;
global.document = dom.window.document;
if (!dom.window.matchMedia)
  dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });

const mermaid = (await import(new URL("node_modules/mermaid/dist/mermaid.esm.min.mjs", VAL))).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

const html = readFileSync(new URL("lessons_deck.html", import.meta.url), "utf-8");
const line = html.split("\n").find((l) => l.startsWith("const MMD = "));
if (!line) {
  console.log("MMD array not found in HTML");
  process.exit(1);
}
const MMD = JSON.parse(line.slice("const MMD = ".length).replace(/;\s*$/, ""));
console.log("extracted", MMD.length, "diagrams from the built HTML");

let fail = 0;
for (const [id, code] of MMD) {
  try {
    await mermaid.parse(code);
  } catch (e) {
    fail++;
    console.log("FAIL  " + id + " :: " + String(e.message || e).split("\n")[0]);
  }
}
console.log(fail ? "RESULT: " + fail + " FAILED" : "RESULT: ALL " + MMD.length + " EMBEDDED DIAGRAMS PARSE CLEAN");
process.exit(fail ? 1 : 0);
