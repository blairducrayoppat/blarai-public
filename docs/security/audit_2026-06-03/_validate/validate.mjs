// Validate every deck diagram against the REAL mermaid parser (jsdom-backed).
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

const deck = JSON.parse(readFileSync(new URL("../deck_outline.json", import.meta.url), "utf-8"));
const items = [];
(deck.system_diagrams || []).forEach((s, i) => items.push(["sys[" + i + "] " + (s.title || "").slice(0, 30), s.mermaid]));
(deck.slides || []).forEach((s) => {
  if (s.mermaid && s.mermaid.trim()) items.push(["slide: " + (s.title || "").slice(0, 30), s.mermaid]);
});

let fail = 0;
for (const [name, code] of items) {
  try {
    await mermaid.parse(code);
    console.log("OK    " + name);
  } catch (e) {
    fail++;
    const m = e && e.message ? String(e.message).split("\n").slice(0, 4).join("  |  ") : String(e);
    console.log("FAIL  " + name + "\n        " + m);
  }
}
console.log(fail ? "RESULT: " + fail + " DIAGRAM(S) FAILED" : "RESULT: ALL DIAGRAMS PARSE CLEAN");
