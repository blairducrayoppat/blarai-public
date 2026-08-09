# BlarAI Portfolio Demo — assembly plan & narrative

Captured live on the Arc 140V dev box, 2026-07-03. Media lives **outside the
repo** at `C:/Users/mrbla/Videos/BlarAI_portfolio/` (raw clips, shots, title
cards, final cut). This doc is the script + edit list.

## The story arc

A private AI that runs entirely on one 32 GB laptop — voice, vision, memory,
image generation, safe web access, and the ability to build software — with a
hardware-rooted security design underneath. Ordered feature-first, with the
security/privacy story carried in captions and a closing summary.

## Segments (in final order)

| # | Source | Beat | Caption (lower-third) |
|---|--------|------|------------------------|
| T0 | title card | Cold open | **BlarAI — a private AI that runs entirely on your own laptop.** No cloud. No account. Your data never leaves the machine. |
| 1 | `01_boot.mkv` | The secure boot | Every launch **verifies the model's signature**, mints **per-boot mTLS certs**, and starts a **zero-network VM**. |
| 2 | `02_chat.mkv` | It talks + acts | A local 14B model answers, and calls **live tools** (date/time) — all on the GPU. |
| 3 | `03_knowledge.mkv` | It remembers | Ingest a document → **review → approve** → recall it in a **fresh session**. Stored **encrypted at rest**. |
| 4 | `04_vision.mkv` | It sees | Attach a photo; the vision model **describes the scene** — offline. |
| 5 | `05_imagegen_trimmed.mkv` (or 017 still) | It creates | **Generate images on-device** — born encrypted, never uploaded. |
| 6 | `06_voice.mkv` | It listens & speaks | **Speak to it, it speaks back** — Whisper + a local voice, no cloud STT/TTS. |
| 7 | `07_websearch.mkv` | It reaches the web — safely | The **first** web request each session needs your **fingerprint** (Windows Hello). One governed door; everything else stays offline. |
| 8 | `013_deny_test.png` (still, 4s) | It refuses | A destructive request is **refused** — dangerous actions are denied by design. |
| 9 | `08_dispatch_setup.mkv` + dispatch run + result | It builds software | Describe an app → it **plans + shows acceptance criteria** → swaps to a 30B coder → **an agent fleet builds & tests it** → restores itself. |
| T1 | closing card | The design | **Security by architecture:** hardware-sealed keys (TPM) · signed model weights · one fingerprint-gated network door · born-encrypted storage · built by directing AI agents, documented in the open. |

## Edit spec

- **Canvas** 1920×1080, 30fps, H.264 (yuv420p), CRF 20. Source is 2560×1600 →
  scale to 1920×1200 then pad/crop to 1080p, or scale-to-fit width with letterbox.
- **Title cards**: Pillow-rendered PNGs (dark `#0d0d0d`, amber `#f5a623` accent,
  system font) → 4s each with a 0.5s fade. See `make_titles.py`.
- **Lower-third captions**: burned per segment via ffmpeg `drawtext` (semi-opaque
  bar, white text) OR a Pillow overlay strip. Timed to the segment.
- **Speed**: trim dead air; optionally 1.25× the long "thinking" pauses (keep the
  first token visible so it reads as real). Voice + web-search segments keep real
  time so the spoken audio and the fingerprint beat land.
- **Audio**: `06_voice.mkv` keeps its real audio (the spoken reply). All other
  segments are silent screen captures — leave silent or lay a single quiet
  ambient bed UNDER the whole cut at low level (optional; the deck lesson about
  irrelevant sound applies less to a watched highlight reel than to a live talk,
  but keep it subtle if used).
- **Trim `05_imagegen`**: cut BEFORE the gallery overlay opens (the gallery
  contains content unsuitable for a hiring portfolio — quarantined). Use only the
  `/imagine` → inline watercolor result portion.

## Assembly command sketch (run after fleet completes)

1. `make_titles.py` → title/closing/caption PNGs.
2. Per segment: `ffmpeg -i raw/NN.mkv -vf "scale=1920:-2,drawtext=..." -c:v libx264 -crf 20 work/NN.mp4`
3. Title cards → 4s clips: `ffmpeg -loop 1 -t 4 -i cards/T0.png -vf fade... work/T0.mp4`
4. Concat via `concat` demuxer → `final/BlarAI_demo.mp4`.

## Operator review gate

The final cut is Blair's to review before any sharing/publishing — his
portfolio, his call. Nothing here is uploaded anywhere by the build.
