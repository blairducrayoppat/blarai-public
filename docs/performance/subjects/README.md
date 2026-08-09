# Measurement subjects

Input files that recorded probes consume. They are tracked so that a measurement
in `docs/performance/` can be **re-run and checked**, not merely read.

A recorded result whose subject is missing is indistinguishable from a fabricated
one at any later date. That is the failure this directory exists to prevent, and
`tests/security/test_measurement_subjects.py` enforces it: a repo-relative media
path named by a committed script must resolve to a tracked file.

## Contents

| subject | consumed by | notes |
|---|---|---|
| `blarai_lighthouse3.png` | `scripts/probe_35b_multimodal_quality.py` (`rendered_scene`) | UC-010 generated art — a lighthouse seascape |
| `hand2.png` | `scripts/probe_35b_multimodal_quality.py` (`detail_render`) | UC-010 generated art — three people at a cafe table; chosen for anatomical detail |

The third case of the 35B probe, `logo_graphic`, reads `branding/blair_glow.png`,
which is tracked in its own right and stays there.

The 2026-07-22 gemma4 vision probe's ground-truth source is **already banked** beside
the renders it produced, at
`docs/performance/ov_cache_answer_flip_2026-07-22/subjects/cook_ok.html` (tracked
since `56fd5782`). A byte-identical copy of it sat untracked at the repo root as
`cook_test.html`; that copy was the duplicate, not the original. It is not mirrored
here — one provenance chain, one home.

## Provenance of the relocation (#1318)

Both files sat **untracked at the repository root** when the measurements that cite
them were taken. Records written before 2026-08-07 therefore describe them as being
at the repo root, and those descriptions were accurate when written:

- `docs/performance/probe_35b_multimodal_quality_2026-07-16_21-54-51.json`
- `docs/performance/gemma4-vision-instrument-probe-2026-07-22.json` / `.md`

They were moved here, unmodified, on 2026-08-07. Byte-for-byte the subjects are
what those runs consumed; only their path changed. Nothing in those records was
edited — a measurement record is history, and history is not rewritten to match a
tidier present.

**A correction belongs here too.** #1318 originally claimed three subjects were
unbanked. An independent review of the change found the third, `cook_test.html`,
was byte-identical to a file tracked since 2026-07-30 — the working-tree copies
differed only by line endings, which is why a first-pass `md5sum` made them look
distinct. Two subjects were genuinely missing; the third claim was wrong, and it
was wrong in the direction this whole arc is about, so it is recorded rather than
quietly dropped.

## Adding a subject

Commit the file here in the same change as the script that reads it. A probe whose
subject arrives later is a probe that was unreproducible in between, and the gap
does not announce itself.
