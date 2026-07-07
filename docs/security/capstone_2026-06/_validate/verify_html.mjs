// Verify the EXACT diagram strings embedded in the generated HTML parse cleanly
// (this tests what the browser actually hands mermaid.render()).
// Mirrors docs/security/audit_2026-06-03/_validate/verify_html.mjs.
import { JSDOM } from "jsdom";
import { readFileSync } from "fs";

const dom = new JSDOM("<!DOCTYPE html><body></body>");
global.window = dom.window;
global.document = dom.window.document;
if (!dom.window.matchMedia) dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

const html = readFileSync(new URL("../capstone_presentation.html", import.meta.url), "utf-8");
const line = html.split("\n").find((l) => l.startsWith("const MMD = "));
if (!line) {
  console.log("MMD array not found in HTML");
  process.exit(1);
}
const MMD = JSON.parse(line.slice("const MMD = ".length).replace(/;\s*$/, ""));
console.log("extracted", MMD.length, "diagrams from the HTML");

let fail = 0;
for (const [id, code] of MMD) {
  try {
    await mermaid.parse(code);
    console.log("OK    " + id);
  } catch (e) {
    fail++;
    console.log("FAIL  " + id + " :: " + String(e.message || e).split("\n")[0]);
  }
}
console.log(fail ? "RESULT: " + fail + " FAILED" : "RESULT: ALL EMBEDDED DIAGRAMS PARSE CLEAN");
