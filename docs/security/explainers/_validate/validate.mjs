// Validate every explainer-deck diagram against the REAL mermaid parser (jsdom-backed).
// Mirrors the main capstone deck's _validate/validate.mjs, iterating both explainer outlines.
import { JSDOM } from "jsdom";
import { readFileSync } from "fs";

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", { pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
if (!dom.window.matchMedia) {
  dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
}

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose", htmlLabels: true });

const outlines = ["attestation_outline.json", "host_guest_outline.json"];
let fail = 0;
let count = 0;
for (const f of outlines) {
  const deck = JSON.parse(readFileSync(new URL("../" + f, import.meta.url), "utf-8"));
  for (const s of deck.slides || []) {
    if (s.mermaid && s.mermaid.trim()) {
      count++;
      try {
        await mermaid.parse(s.mermaid);
        console.log("OK    " + f + " :: " + (s.title || "").slice(0, 30));
      } catch (e) {
        fail++;
        console.log("FAIL  " + f + " :: " + (s.title || "").slice(0, 30) + "\n        " + String(e.message || e).split("\n").slice(0, 3).join("  |  "));
      }
    }
  }
}
console.log(fail ? "RESULT: " + fail + " DIAGRAM(S) FAILED" : "RESULT: ALL " + count + " DIAGRAMS PARSE CLEAN");
