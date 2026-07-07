// Diagnose what the browser hands mermaid for each <pre class="mermaid"> in the
// actual generated HTML, and which extraction parses cleanly.
import { JSDOM } from "jsdom";
import { readFileSync } from "fs";

const html = readFileSync(new URL("../security_presentation.html", import.meta.url), "utf-8");
const dom = new JSDOM(html);
global.window = dom.window;
global.document = dom.window.document;
if (!dom.window.matchMedia) dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

const pres = [...document.querySelectorAll("pre.mermaid")];
console.log("mermaid blocks:", pres.length);
console.log("--- block[0] textContent (first 160) ---");
console.log(JSON.stringify(pres[0].textContent.slice(0, 160)));
console.log("--- block[0] innerHTML (first 160) ---");
console.log(JSON.stringify(pres[0].innerHTML.slice(0, 160)));

let i = 0;
for (const el of pres) {
  i++;
  for (const [label, src] of [["textContent", el.textContent], ["innerHTML", el.innerHTML]]) {
    try {
      await mermaid.parse(src);
      console.log(`block ${i} via ${label}: OK`);
    } catch (e) {
      console.log(`block ${i} via ${label}: FAIL :: ${String(e.message || e).split("\n")[0]}`);
    }
  }
}
