// Fake srt-win for offline self-test: emulates `wfp verify --target T`.
// FAKE_MODE: all-blocked | v6-open | v4-open
const args = process.argv.slice(2).filter(x => x !== '--srt-win')
const T = args[args.indexOf('--target') + 1]
const mode = process.env.FAKE_MODE
const v6 = T.startsWith('[')
const open = (mode === 'v6-open' && v6) || (mode === 'v4-open' && !v6)
if (args[0] !== 'wfp' || args[1] !== 'verify' || !T || !['all-blocked','v6-open','v4-open'].includes(mode)) {
  console.error('fake: bad args/mode'); process.exit(64)
}
console.log(JSON.stringify({ egress_probe: open ? 'connected' : 'blocked', target: T, runner_exit: open ? 3 : 0 }))
console.error(open ? 'CONNECTED (fake)' : 'BLOCKED (fake)')
process.exit(open ? 3 : 0)
