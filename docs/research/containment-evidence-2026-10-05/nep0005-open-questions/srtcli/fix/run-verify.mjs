// Usage: node run-verify.mjs --tree stock|patched --exe <srt-win.exe> [--prepend <script.mjs>]
// Spawner is { exe, prependArgs } exactly as resolveSrtWin() builds it
// (prependArgs = ['--srt-win']). --prepend is for the offline self-test
// only: exe is then node.exe and the fake script is placed before '--srt-win'.
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const a = process.argv.slice(2)
const get = k => { const i = a.indexOf(k); return i >= 0 ? a[i + 1] : undefined }
const tree = get('--tree'), exe = get('--exe'), prepend = get('--prepend')
if (!['stock', 'patched'].includes(tree) || !exe) {
  console.error('usage: run-verify.mjs --tree stock|patched --exe <srt-win.exe> [--prepend <script>]')
  process.exit(2)
}
const root = path.join(here, tree, 'anthropics-sandbox-runtime-24eb39e')
const mod = await import(pathToFileURL(path.join(root, 'dist', 'index.js')).href)
const srtWin = prepend
  ? { exe, prependArgs: [path.resolve(prepend), '--srt-win'] }
  : mod.resolveSrtWin({ path: exe })
try {
  const result = await mod.verifyWindowsWfpEgress({ srtWin })
  console.log(JSON.stringify({ tree, ok: true, result }))
} catch (e) {
  console.log(JSON.stringify({ tree, ok: false, code: e.code ?? null, message: String(e.message) }))
}
process.exit(0)
