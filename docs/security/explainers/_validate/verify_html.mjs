// Verify the EXACT diagram strings embedded in each generated explainer HTML parse cleanly.
// Mirrors the main capstone deck's _validate/verify_html.mjs, iterating both explainer HTMLs.
import { JSDOM } from "jsdom";
import { readFileSync } from "fs";

const dom = new JSDOM("<!DOCTYPE html><body></body>");
global.window = dom.window;
global.document = dom.window.document;
if (!dom.window.matchMedia) dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

const htmls = ["attestation.html", "host_guest.html"];
let fail = 0;
let total = 0;
for (const f of htmls) {
  const html = readFileSync(new URL("../" + f, import.meta.url), "utf-8");
  const line = html.split("\n").find((l) => l.startsWith("const MMD = "));
  if (!line) {
    console.log(f + ": MMD array not found");
    fail++;
    continue;
  }
  const MMD = JSON.parse(line.slice("const MMD = ".length).replace(/;\s*$/, ""));
  for (const [id, code] of MMD) {
    total++;
    try {
      await mermaid.parse(code);
      console.log("OK    " + f + " :: " + id);
    } catch (e) {
      fail++;
      console.log("FAIL  " + f + " :: " + id + " :: " + String(e.message || e).split("\n")[0]);
    }
  }
}
console.log(fail ? "RESULT: " + fail + " FAILED" : "RESULT: ALL " + total + " EMBEDDED DIAGRAMS PARSE CLEAN");
