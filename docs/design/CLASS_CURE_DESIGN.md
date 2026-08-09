# Class cure design — the two families of "an instrument reports a pass it did not measure"

**Ticket:** #1241 (census) · #1242, #1243, #1195, #1237, #1239 (siblings)
**Status:** DESIGN. No production code written. Branch `docs/1241-class-cure-design` off `0f0614a3`.
**Author's discipline:** every claim below is labelled **MEASURED** (with `file:line`, read on disk in this
worktree) or **DERIVED** (reasoning from measured facts). The census that commissioned this design cited a
wrong line number in a document about false claims; this document is written against that scar.

---

## 0. Verdict on the partition, before anything is designed

The brief asked me to say plainly if the two-family partition is wrong. **It is right, and I can now state
the reason more precisely than the censuses did.**

The families are not distinguished by symptom, nor even by cure. They are distinguished by **where the single
point of truth sits relative to the people who consume it**:

| | Family A | Family B |
|---|---|---|
| Truth | ONE value (the operator's answer) | MANY producers (each walk, scan, lint) |
| Consumers | MANY carriers (~11 artifacts) | ONE render (the card / verdict) |
| Defect | a consumer drifts from the producer | a producer's limit never reaches the consumer |
| Cure sits at | the **producer** — derive consumers from it | the **consumer** — refuse to render without coverage |

**DERIVED:** this is why a newtype closes zero Family A rows. A type constrains what a *consumer* may do with
a value. Family A's consumers each hold a validly-typed, individually-correct `str`. There is no ill-typed
state to forbid — the defect is that there are eleven of them. Conversely a derivation function closes zero
Family B rows, because Family B has no second copy to delete; it has one copy whose *provenance* is missing.

That is the "same word, opposite end of the pipe" observation from the propagation census, and it holds.

### One correction to the census, and one new MEASURED row

**Correction (minor, does not change the design).** #1241 says `RegressionFinding.measured` is "read
NOWHERE". Precisely: it IS serialised at `tools/dispatch_harness/green_quality/__init__.py:153`
(`"regression_measured": self.layer1.regression.measured`) — **MEASURED**. What is true, and is the real
defect, is that **no band, card, findings-line or KPI consults it**: `layer1.py:807-836` `findings()` branches
only on `.regressed` / `.changed` (`:812-815`), and `__init__.py:428-441` `render_kpi` renders a
not-measured count **for security only** (`:440`). So the value is *written to disk and never read by
anything that decides or renders*. That is worse than unread — it is evidence of intent, banked and ignored.

**NEW MEASURED ROW — and it is the sharpest single finding in this document.**

#1241 row 2 says `cp.returncode` is never read and calls the consequence "live on any deliverable whose
config makes ruff exit 2." **It is live on every night this project runs, right now, and it defeats the
#1189 fix on precisely the condition #1189 was written for.**

`layer1.py:761-778` (**MEASURED**, read in full) runs `[sys.executable, "-m", "ruff", …]`, catches only
`OSError`/`TimeoutExpired`, never inspects `cp.returncode`, and parses `json.loads(cp.stdout or "[]")`.

I ran it (**MEASURED**, this box, this worktree, 2026-07-31):

```
returncode: 1
stdout repr: ''
stderr repr: 'C:\\Python314\\python.exe: No module named ruff\n'
PARSED -> [] -> run_ruff_advisory would return 0
```

`0` is not `None`. So `findings()` takes `layer1.py:834-835` and emits:

> `ruff: 0 advisory findings (measured)`

#1195 item 5 records (**MEASURED**, ticket description) that ruff **is not installed**. #1189's entire
purpose was that "a skipped lint renders identically to a clean one." Its fix distinguishes `None` from `0`
in the *renderer* (`:829-835`) and left the producer minting `0` on the missing-module path. **The fix is
defeated on its own motivating condition, and the word `(measured)` is printed on a measurement that did not
happen.**

And the gate that certifies that fix, `tests/integration/test_green_quality.py:904-915` (**MEASURED**),
asserts `'["ruff", "check"' in src` via `inspect.getsource`. It passes today. It would pass if the entire
function body were deleted and replaced by that string in a comment.

> ### CORRECTION, 2026-07-30, by the session that merged this branch — MEASURED
>
> **The escalation in this section is wrong and is retracted. The finding is not.**
>
> This section claims the defect is "live on every night this project runs" because ruff is not
> installed. Measured on this box:
>
> ```
> C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m ruff --version
> ruff 0.16.1          (exit 0)
> ```
>
> and `agentic-setup/scripts/run-battery-night.ps1:101` binds the battery to that exact
> interpreter: `$Python = "$BlarRuntimeRoot\.venv\Scripts\python.exe"`. `run_ruff_advisory`
> invokes `[sys.executable, "-m", "ruff", …]`, so on the nightly path ruff resolves and runs.
> The probe recorded above ran `C:\Python314\python.exe`, which its own captured stderr names —
> a different interpreter from the one the battery uses.
>
> The supporting citation ("#1195 item 5 records (MEASURED, ticket description) that ruff is not
> installed") is a **ticket description standing in for a measurement of the machine.** That is
> *Documentation is NOT evidence* applied to our own board, and it is what carried the
> escalation.
>
> **What survives, reproduced independently:** an empty stdout becomes `[]` becomes `0`, a
> measured zero on the path the docstring promises returns `None`. Its real triggers are any
> ruff invocation that errors with empty stdout (a malformed config in a generated deliverable
> makes ruff exit 2 — the census's original framing), and any harness path under an interpreter
> without ruff; one exists here, `fleet-lib.ps1:707`'s `acp_coder.py` under Python 3.14.
>
> Slice 1 and the fix are unchanged. Recorded here rather than silently amended, because this
> document's own §1 thesis is that a claim must land on an artifact, and the artifact said
> otherwise. Full record on #1244.

This one row is the whole thesis of the document in miniature, so I will state the thesis now.

---

## 1. THE THESIS — the property that separates a control that holds from one that gets satisfied

> **A control whose subject is the SOURCE TEXT is satisfiable by editing the source text.
> A control whose subject is a PRODUCED ARTIFACT is not.**

This single line explains every measured outcome in the census, and it is the design rule both cures obey.

**MEASURED evidence, four independent instances:**

| control | subject | outcome |
|---|---|---|
| `test_green_quality.py:904-915` — `inspect.getsource` + `in src` | **source text** | passed on unreachable code (#1241 row 1) |
| `test_doctrine_freshness.py:389` vocabulary lint (scope `:278-282`, phrases `:288-299`) | **source text** | missed all nine claim rows; extending it convicts 4 MEDIUM, 0 HIGH |
| `traceability.py:120-125` `NOT_MEASURED` static tuple, emitted at `:661` `list(NOT_MEASURED)` | **source text** (prose) | a disclosure certifying its own completeness, derived from nothing about the run |
| `test_no_new_raw_spawn_sites.py` — AST-walks the live tree, allowlist may only shrink | **produced artifact** (the tree) | **held**; the ratchet family is 2/2 and the only mechanism that survived a PowerShell refactor |

The brief's hardest constraint — *"a control in this class tends to be checkable by inspection and therefore
satisfiable by inspection"* — is precisely the statement that most controls in this repo took the source text
as their subject. `_ = cp.returncode` satisfies "returncode never read" **because that check reads source**.
Nothing satisfies "the produced card does not contain the word `cli`" except the card not containing it.

**This is why I propose no lint, in either design.** Both cures below are built so their assertions land on
artifacts, and both are backed by the one mechanism this repo has measured as surviving: the **ratchet**.

---

## 2. FAMILY A — N carriers of one value

### 2.1 What is measured

`_choose` (`services/ui_gateway/src/dispatch_coordinator.py:1726-1813`, **MEASURED**) resolves the operator's
platform answer and threads it by calling:

- `acc.apply_clarification(...)` → `shared/fleet/acceptance.py:344-367` (**MEASURED**) — sets `surface`,
  clears `candidates` on the build_plan. Pure, correct, locked.
- `acc._thread_build_fields(...)` → `acceptance.py:3027-3062` (**MEASURED**) — which calls
  `_task_build_fields(build_plan)` at `:3060`.

`_task_build_fields` (`acceptance.py:2991-3016`, **MEASURED**) returns exactly **three** fields:
`surface`, `language_hint`, `complexity`. That is the census's "3 carriers of ~11", confirmed at the line.

**It is a hand-written list — and worse, it is a hand-written list whose docstring explains why it is
short.** `:2994-2996` justifies the three by what *the fleet reads today* (`$t.complexity`, `$t.surface`).
Every carrier added since — task name, graded criterion, exam command, seed path, asset spec, four floors —
was authored elsewhere, at plan time, and this list was never revisited. **DERIVED:** any fix shaped as a
longer hand-written list is correct until carrier N+1, which is the mechanism #1237 and #1220 are both
instances of.

`_choose`'s own docstring asserts the safety property that is false: `:1733` *"only `surface` changed; the
test block is untouched"* and `:1781-1784` *"it does NOT touch the folded test block, so re-stamping is
safe."* **MEASURED.** That is exactly right about aliasing and exactly wrong about correctness: not touching
the test block is the *defect*, because the test block encodes the surface the operator rejected. This is
LESSONS lesson 47 (`LESSONS.md:342`, ↺3 — *a comment claiming a property the code does not enforce*) sitting
four lines above the code that violates it.

### 2.2 The cure — derive, never re-stamp

Extract the post-build-signal tail of `generate_plan` as a pure re-entrant derivation:

```python
def re_derive_from_surface(spec: AcceptanceSpec, tasks: list[dict], *,
                           generate_fn, ...) -> tuple[AcceptanceSpec, list[dict]]:
    """Re-author EVERY artifact downstream of the build signal from the spec's CURRENT surface.

    The single producer of every surface-dependent carrier. `generate_plan` calls it on the
    first pass; `_choose` calls it again after the operator answers. Called twice with the
    same surface it is idempotent; called with a new surface it regenerates rather than
    annotates."""
```

Both `generate_plan` and `_choose` call it. `_choose` stops calling `_thread_build_fields` as its threading
mechanism (the function stays — it is still correct for the *fallback* path at `:1758`, where no surface was
chosen and there is nothing to re-derive).

**This closes late-arrival (temporal) and one-of-N (spatial) together** because after it there is exactly one
place a surface-dependent artifact is authored. **DERIVED**, and it matches both the #1237 builder's and the
propagation census's independent assessments.

### 2.3 The lock — and this is the half that matters more than the refactor

**MEASURED:** every HIGH Family-A row reads `Test: NONE`, and no test in either repo pairs any two carriers
of anything. `tests/integration/test_acceptance.py` and `test_dispatch_coordinator.py` reference
`apply_clarification`/`_thread_build_fields`, but assert on the build_plan and the task fields — the carriers
that were already correct.

The naive lock is to enumerate the carriers and assert each agrees. **That lock recreates the defect it
cures**: the enumeration is a hand-written list of carriers someone remembered, and carrier N+1 is invisible
to it. This is the trap I want to name loudly, because it is the shape a hurried implementer will reach for.

**The lock must assert over the whole produced artifact, negatively.**

```python
def test_no_carrier_of_the_plan_mentions_the_surface_the_operator_REJECTED():
    """Drives the REAL parse_dispatch_command -> handle_command -> generate_plan -> _choose
    on a pristine empty repo, answers the platform menu with the browser option, then
    serialises EVERYTHING the operator's answer should have reached and asserts the rejected
    surface's vocabulary does not survive anywhere in it.

    Completeness by construction: the assertion walks the serialised artifact, so a carrier
    added tomorrow is covered the day it is added, with no list to update. That is the whole
    point -- an enumerated carrier list would be the very defect under cure."""
    artifact = json.dumps({"spec": asdict(spec), "tasks": tasks, "card": rendered_card})
    for token in REJECTED_SURFACE_VOCAB["cli"]:        # "cli", "command-line", "test_cli.py"
        assert token not in artifact.lower(), _locate(artifact, token)
```

Plus a small number of **positive** assertions at the load-bearing few — the graded criterion and the exam
command must mention the *chosen* surface — because a negative-only test passes on an empty artifact.

Two properties worth stating explicitly:

- **Its subject is the produced artifact, not the source.** There is no textual dodge. To make it pass you
  must make the carriers actually agree. This is §1's thesis applied.
- **It must FAIL on today's tip.** That is #1243's stated predicate and it is also the toggle-proof: the
  RED run on `0f0614a3` *is* the demonstration that the lock has teeth, and it should be pasted into the
  ticket before the fix lands, not after.

**The allowlist question, answered honestly.** Some legitimate strings quote the rejected surface — the
clarification record stores the question, which lists both options. Those need an allowlist, and an allowlist
is a hand-written list, which is the thing I just argued against. The resolution: the allowlist is keyed by
**JSON path** (`spec.clarifications[*].question`), not by token, and it is a **ratchet** — a companion test
asserts the allowlist may only shrink, exactly as `test_allowlist_not_stale` does for raw-spawn sites
(`test_no_new_raw_spawn_sites.py:40-43`, **MEASURED**: *"the known-debt count can only go DOWN"*). A new
exempt path is a reviewer's deliberate act with a written justification, never a silent slip.

### 2.4 Why Family A's cure cannot be satisfied by inspection

The derivation is a *production* control, so the honest argument is different from Family B's and I will not
blur them.

- The **test** cannot be satisfied by inspection: its subject is the serialised plan (§1).
- The **derivation** can be bypassed — someone can author a new surface-dependent string outside
  `re_derive_from_surface`. Nothing in Python prevents that.
- **What catches the bypass is the same test**, automatically, because the new string lands in the same
  serialised artifact the negative assertion walks. **This is the design's strongest property: the bypass and
  the detector are the same surface.** A carrier added outside the derivation is a carrier the test now sees.

That is a complete argument, and it does not depend on anyone remembering anything.

---

## 3. FAMILY B — N sites each deciding whether to admit a limit

### 3.1 What is measured

The reference implementation and the counter-example sit in the same package:

- `security.py:318-321` (**MEASURED**): `is_clean()` → `return self.measured and not self.findings`, with a
  docstring naming the rule — *"An unmeasured scan is never clean — that is the fail-closed reading of a
  fail-soft control."* `security.measured` is consulted at **five** sites: `band.py:74`, `card.py:101, 106,
  107`, `__init__.py:423` (**MEASURED**, grep). Security narrows the most and is the cleanest.
- `layer1.py:385-391` (**MEASURED**): `CraftFinding` is `flagged: bool` + `detail: str`. No coverage field
  exists, so `flagged=False` is indistinguishable from "the walk raised `OSError` and I substituted `[]`"
  (#1241 row 8, `layer1.py:413-428`).
- `SeedDivergenceFinding` (`layer1.py:570-585`, **MEASURED**) is the working middle case: a `measured`
  property derived from `status`, consulted at exactly **one** site (`layer1.py:821`), which is the one
  unmeasured case `findings()` reports out loud.

**DERIVED:** the difference between these three is not care, diligence or review. It is whether the type
*can* express "clean" without "measured". Where it cannot, no author has ever got it wrong. Where it can,
authors get it wrong repeatedly and their reviewers do too.

### 3.2 The cure — a coverage token the walk mints

Not a `bool measured` field. A `bool` is the thing that already failed: it is writable by hand, defaults
plausibly, and `measured=True` is as cheap to type as `measured=False`.

```python
@dataclass(frozen=True)
class Coverage:
    """What a walk actually examined. Constructed ONLY by `walked()` / `unmeasured()`.

    `examined`/`skipped`/`capped` are computed BY the walk, never written by a caller: the
    counters increment at the `continue`/`break`/`except` that causes them, so a limit cannot
    be taken without being counted in the same statement."""
    examined: int
    skipped: int      # unreadable, over-size, unparseable -- #1241 rows 4, 5, 7
    capped: bool      # the walk stopped early -- row 13
    def measured(self) -> bool: return self.examined > 0
    def complete(self) -> bool: return self.measured() and not self.skipped and not self.capped
```

Every advisory finding type carries one, and the render consults it:

```python
@dataclass(frozen=True)
class CraftFinding:
    flagged: bool
    detail: str
    coverage: Coverage          # NO DEFAULT -- every construction site must supply one
    def is_clean(self) -> bool:
        return self.coverage.measured() and not self.flagged
```

`layer1.py:807-836` `findings()`, `band.py`, `card.py` and `render_kpi` consult `.is_clean()` /
`.coverage` the way they already consult `security.measured` (`__init__.py:436-437` **MEASURED** already
states the doctrine — *"the unmeasured count is rendered even at zero"* — and applies it to security only).

**Two structural details that carry the design:**

1. **No default on `coverage`.** A dataclass field without a default makes every existing construction site
   a compile-time (well, construction-time) error until it supplies one. That is what converts a refactor
   from "find all the sites" into "the machine finds them for you", and it is why this migrates safely.
2. **The counter increments at the statement that causes it.** `green_audit.py:632-634` does
   `if source is None: continue` with no counter (#1241 row 4 — **the one verdict-changing row**,
   GREEN→PARKED-HONEST). `security.py:890-891` carries an `unreadable` counter for the identical loop.
   The cure is to make the skip and the count the same statement, so a future `continue` that forgets is
   visibly different from its neighbours.

### 3.3 The `run_ruff_advisory` case — the same cure at the producer

The type fixes the render. The §0 finding shows the *producer* also mints a false zero, and no result type
catches a genuinely-wrong number. That needs its own one-line fix in the same slice:

```python
if cp.returncode not in (0, 1):     # ruff: 0 = clean, 1 = findings; anything else did not lint
    continue                        # -> falls through to `return None` == NOT RUN
```

**MEASURED** justification for the constants: this box returns `1` with empty stdout for *module not found*,
which collides with ruff's own "findings present" code. So `returncode` alone is insufficient and the real
predicate is `returncode in (0, 1) and cp.stdout.strip()` — an empty stdout on `1` means ruff never ran.
I flag this as the one place where I am designing against a **measured collision** rather than a documented
contract, and the implementer should verify against an installed ruff before pinning it.

### 3.4 The lock, with its toggle-proof

Two tests, both artifact-subject:

```python
def test_an_unmeasured_craft_walk_cannot_render_as_clean():
    """Positive control: point the REAL audit at a directory it cannot read, then assert the
    rendered card and the KPI both NAME the absence. Drives audit_layer1 + build_card, not
    the dataclass in isolation -- the mock-shape divergence this project has paid for twice."""

def test_the_clean_render_FAILS_when_the_coverage_gate_is_removed():
    """The toggle-proof. Monkeypatches Coverage.measured to `lambda self: True` -- the exact
    shape of the pre-fix bug -- and asserts the first test now FAILS. Without this, a green
    first test cannot distinguish `secure` from `the probe never reached the control`
    (security_by_design principle 12)."""
```

And the ratchet, which is what makes it survive:

```python
def test_no_advisory_finding_type_lacks_a_coverage_field():
    """AST-walks green_quality/ + green_audit.py for @dataclass types whose name ends in
    `Finding`/`Result`, and fails naming any that has no `coverage` field. KNOWN_EXEMPT may
    only SHRINK (the ratchet) -- a new advisory type without coverage cannot land silently."""
```

**Its subject is the AST of the live tree, not a phrase list.** Adding a type is a produced artifact; you
cannot satisfy it with a comment.

### 3.5 Why Family B's cure cannot be satisfied by inspection — stated honestly, including where it can

The brief asked me to argue this or say plainly that I cannot. **I can argue it for the realistic failure
mode and not for the adversarial one, and the distinction matters.**

`Coverage(examined=1, skipped=0, capped=False)` is typeable by hand. **A determined author can fake it.** Any
claim that this type is unfakeable would be an overclaim — which is the defect class this whole document
exists to cure, so I will not make it.

What the design actually delivers, in descending strength:

1. **The default is no longer honest-looking.** These are momentum defects, not adversarial ones — every
   census row is an author on the path of least resistance (`except OSError: files = []`, `if source is None:
   continue`). Making `coverage` mandatory means the *lazy* path no longer produces a clean verdict; it
   produces a construction error. That retargets the fix at the actual population.
2. **Faking it requires a visible lie.** `_ = cp.returncode` is invisible in review — it looks like tidy
   code. `Coverage(examined=1, skipped=0, capped=False)` next to a bare `except OSError` is a hand-written
   count contradicting the statement above it. It moves the defect from *invisible* to *reviewable*, which is
   a real and modest gain, honestly sized.
3. **The mint sites are ratcheted.** If the implementer takes the stronger option — `Coverage` constructible
   only via `walked()`/`unmeasured()` module factories, with an AST gate enumerating the call sites,
   shrink-only — then a hand-constructed `Coverage` fails a gate whose subject is the call graph. This is the
   only part of the design that is genuinely not satisfiable by inspection, and I recommend it, while noting
   it is the slice most likely to be dropped under time pressure.

**The honest limit, recorded because an unstated gap is the thing this hunts:** none of this reaches a
walk that examines the wrong thing correctly and counts it honestly. Coverage answers *how much*, never
*of what*. `traceability.py:955-958`'s first-glob-match (#1241 row 11) reports `examined=1` truthfully while
the 1 is the wrong file. **That row is NOT closed by this design** — see §5.

---

## 4. The ceremony step (#1242 and siblings)

**MEASURED:** eight of nine claim-rot rows are one idiom — a claim written at build time naming the config
key that gates it, never reopened at the ceremony that flipped that key — clustering by ceremony date
(2026-06-27 #670, 07-02 web_search, 07-11 #775, 07-14/15 coordinator), not by module.

**MEASURED:** `docs/runbooks/` holds ten go-live/ceremony runbooks as separate files (`advanced_intake_*`,
`web_search_go_live.md`, `headless_coding_dispatch_go_live.md`, `uc010_image_gen_go_live.md`,
`dispatch_project_memory_go_live.md`, `at_rest_encryption_ceremony.md`, `manifest_signing_ceremony.md`, …).

**Therefore the step must not be pasted into ten files** — that is Family A's defect applied to prose, and
runbook eleven would be born stale. One shared file, referenced by all:

**New: `docs/runbooks/GO_LIVE_COLLATERAL_SWEEP.md`** — a single numbered step every ceremony runbook links
at its close:

> ## Step: sweep the collateral this flip just falsified
>
> You have just changed what is true. Every document, docstring, comment and test that named the key you
> flipped is now describing the old world, and this is the moment of maximum knowledge about which ones
> those are — nobody will ever again know this flip as well as you know it right now.
>
> 1. Name the config key(s) this ceremony changed, and the file that owns them.
> 2. `git grep -n "<key>"` across BOTH repos (BlarAI and agentic-setup). Every hit is **stale until
>    re-read** — not "probably fine".
> 3. For each hit, either correct it, or replace the restated rule with a pointer to the owning surface
>    (`default.toml`, the runbook). CLAUDE.md `coding_standards` already forbids restating current wiring in
>    docstrings; this is where that rule is actually enforced.
> 4. Grep the operator-facing documents by name — `README.md`, `BLUEPRINT.md`, `PROMPTS.md`. #1242 is the
>    row that proves these are missed: three documents describe a hard gate that `fleet-lib.ps1:2304-2320`
>    made a soft signal under #687.
> 5. Record in the ceremony's ticket: the key, the hit count, and what changed. A sweep with no record is
>    a sweep that did not happen.

**The gate that keeps it from rotting** — same ratchet shape, artifact subject:

```python
def test_every_go_live_runbook_carries_the_collateral_sweep():
    """Every docs/runbooks/*go_live*.md and *ceremony*.md must link GO_LIVE_COLLATERAL_SWEEP.md.
    Deny-by-default: runbook eleven fails the gate on the day it is written, which is the day
    its author is best placed to add the line."""
```

**Its honest limit, with the counter-example the census already found:** `verify-fleet-driver.ps1` DID cite
its oracle and still went stale for three weeks, because either nothing ran it or its red never surfaced.
Citing is necessary and not sufficient — **the cite must be executed and someone must see the failure.**
The gate above is executed by the standing pytest gate, which is the difference.

**Scope note:** #1242's own fix is prose-only. Its ticket is explicit — **do not change `Test-ShouldMerge`**;
the behaviour is LA-decided under #687. This design does not touch it.

---

## 5. Coverage — what each design closes, and what it does NOT

A cure claiming coverage it lacks is the defect under cure, so this table is the most important one here.

| # | row | closed by | honest status |
|---|---|---|---|
| 1 | `test_green_quality.py:904-915` textual gate | B (§3.4 replaces it) | **CLOSED** — deleted and replaced with an artifact-subject test |
| 2 | `layer1.py:766-778` returncode never read | B §3.3 | **CLOSED** + upgraded to live-today (§0) |
| 3 | `battery.py:1942-1955` `{}` triple-meaning sentinel | **NEITHER** | **NOT CLOSED** — see below |
| 4 | `green_audit.py:632-634` unreadable, no counter | B | **CLOSED** — the verdict-changing row |
| 5 | `green_audit.py:436-442` config unreadable | B | **CLOSED** |
| 6 | `RegressionFinding.measured` unconsulted | B | **CLOSED** |
| 7 | `green_audit.py:638-645` unparsed ≡ clean | B | **CLOSED** |
| 8 | `layer1.py:413-428` `except OSError: files=[]` | B | **CLOSED** |
| 9 | `fleet-lib.ps1:1200` `[bool]$StatsPath` | **NEITHER** | **NOT CLOSED** — PowerShell, no type; latent (no caller passes `-StatsPath`) |
| 10 | `coder_test_qa.py:869-871` `not root.is_dir()` | B (partial) | **PARTIAL** — a `Coverage` on the QA result closes it at the seam; the Python side only |
| 11 | `traceability.py:955-958` first-glob-match | **NEITHER** | **NOT CLOSED** — §3.5's stated limit: coverage counts *how much*, not *of what*. Needs `mutation.py:276-284`'s allowlist resolution. **Own ticket.** |
| 12 | `oracle_mutation.py:599-608` `except: pass` | B | **CLOSED** |
| 13 | `green_audit.py:651-652` cap stops the walk | B (`capped`) | **CLOSED** |
| 14 | `fleet-lib.ps1:1191-1198` bare property reads | n/a | **not this class** — errs LOUD (StrictMode throw) |
| — | #1237 / #1243 / #1220 carrier drift | A | **CLOSED** |
| — | #1242 + 8 claim-rot rows | §4 ceremony | 5 of 9 by the census's own measure, incl. one HIGH |
| — | `traceability.py:120-125` static `NOT_MEASURED` | **NEITHER** | **NOT CLOSED** — the census's own sharpest row. See below. |

**Three residuals I am naming rather than quietly absorbing — each FILED, not deferred to memory:**

- **Row 3 (silent absence) → #1245.** #1241's family (b) — a stage contract where every advisory stage emits
  a durable per-card record on its own crash path, with `battery.py:_bank_traceability:1787-1821` as the
  working reference. **This is a third design and I have not written it.** It is genuinely separate: there is
  no verdict object to attach coverage to, because producing one is what failed. It is small (the reference
  exists; two sibling stages need the same treatment). **I did not examine `battery.py` outside the census's
  citations.**
- **Row 11 + the static `NOT_MEASURED` tuple → #1246.** Both are "the disclosure is real but derived from
  nothing about this run." A `Coverage` object does not fix a *statically-authored* disclosure. The cure is
  to compute `not_measured` from the run (emit the L4 entry only when per-criterion attribution was genuinely
  unavailable), and to resolve the oracle glob against an allowlist as `mutation.py:276-284` already does one
  module away. This is the one claim a reader has no independent way to check.
- **Row 9 → #1247.** PowerShell has no type system to lean on. The only mechanism available is the ratchet,
  and `verify-battery-driver-pinning.ps1` / `verify-battery-task-settings.ps1` (**MEASURED**, the repo's 2/2
  surviving ratchets) are both PowerShell — so the mechanism is proven on precisely this surface.

**And the new row from §0 → #1244**, filed URGENT: it is a false `(measured)` printed on the operator's card
tonight, and it is slice 1.

---

## 6. Sequencing against work in flight

**MEASURED:** `fix/1197-quick-path-attribution` exists and is **NOT merged into `main`**
(`git branch --merged main` returns nothing for it; `main` is `0f0614a3`). #1237 is genuinely in flight and
#1243's `blocked-by` predicate is real.

| slice | what | blocked by | why here |
|---|---|---|---|
| **1** | **B-1 (#1244): `run_ruff_advisory` returncode + delete the `inspect.getsource` gate** | nothing | Smallest landable unit, closes a **live-tonight** false `(measured)`, and retires the repo's clearest instance of a source-subject gate. Does not touch `_choose`. **This is the first slice.** |
| 2 | B-2: `Coverage` type + `CraftFinding`/`RegressionFinding` consulted by `findings()`/`band`/`card`/`render_kpi` + toggle-proof + AST ratchet | nothing | The census's "highest-value single change": 4-6 rows, on the only card the operator reads |
| 3 | B-3: `green_audit.py` counters (rows 4, 5, 7, 13) | slice 2 | Row 4 is verdict-changing; needs `Coverage` to exist first |
| 4 | **#1237 merges** | — | Not ours. Changes `_choose`/`apply_clarification` |
| 5 | **A-1: the relational test ALONE, landed RED-then-GREEN** | #1237 | See below — this is the sequencing call worth arguing |
| 6 | A-2: `re_derive_from_surface` + `_choose` calls it | slice 5 | The refactor is what makes slice 5 passable |
| 7 | §4 ceremony file + runbook gate | nothing | Parallelisable; prose-only, no code risk |
| 8 | Residuals, all FILED: **#1245** row 3 stage contract · **#1246** row 11 + static `NOT_MEASURED` · **#1247** row 9 PowerShell ratchet | — | Named in §5 and ticketed, not absorbed |

**The one sequencing call I want to argue rather than assert.** Land the relational test (slice 5) **before**
the refactor, as a RED test with `xfail(strict=True)` citing #1243. Reasons: it makes the RED run the
toggle-proof, permanently, in the repo rather than in a ticket comment; it means the refactor's success
criterion exists before the refactor, so it cannot be quietly redefined to whatever the refactor achieved;
and if slices 6+ are ever deferred, the project is left with an executing, visible statement of a known
defect rather than a ticket. `strict=True` matters — it fails loudly if it starts passing unexpectedly.

**Against #1195:** slices 1-3 and 7 touch the green-quality harness and runbooks, not the battery path, so
they do not consume an attribution window. Slices 5-6 touch the dispatch plan path and **do**. Per
`docs/runbooks/battery_cadence_and_targeted_runs.md` RULE 2 they cannot be stacked with #1195's items on one
night. **DERIVED** from #1195's own stated constraint; I did not re-read the cadence runbook.

---

## 7. For the Lead Architect — plain language

**What is wrong.** Fourteen places in the automatic quality machinery can report "clean" about something they
never actually looked at. Tonight's clearest example: the code-style checker is not installed on this
machine, so it never runs — and the report says *"0 findings (measured)"*. The word "measured" is printed
on a measurement that did not happen. A fix for exactly this was built in June (#1189); I measured it tonight
and it does not work, because it fixed the sentence and not the number behind it.

**Separately**, when you answer a question like *"do you want this in a web browser?"*, your answer reaches
about three of the eleven places that need it. The rest still describe the option you rejected — including
the checklist the coder is graded against. So you can ask for a web app and get a broken build.

**Why one fix will not do.** These look like one problem and are two. The first is *"nobody wrote down what
was skipped"* — cured by changing the shape of the result so a report cannot say "clean" without also saying
how much it looked at. The second is *"your answer was copied to some places and not others"* — cured by
deleting the copies and generating them all from your answer. The cure for one does nothing for the other,
and a single fix claiming to cover both would be the same overclaiming this work exists to stop.

**Cost.** Eight slices. The first is small and closes a wrong statement you are being shown tonight. The
biggest is the fourth and fifth, which touch the planning path and each need their own overnight test window,
so this is roughly a week of evenings rather than one night.

**Risk of doing it.** Low and bounded. Nothing here changes what BlarAI can do or any security setting. The
main risk is that the planning-path change (slices 5-6) reorders how a plan is built, and a mistake there
would show up as worse plans. That is why the test lands first, deliberately failing, so we can see it turn
green for the right reason.

**Risk of doing nothing.** You keep being shown clean bills of health from instruments that did not look —
and you have no way to tell those from real ones, because they are printed in identical words. Three separate
reviews tonight each found rows the others missed, which tells us the population is bigger than fourteen.
Two of the fourteen can flip a verdict, meaning work gets marked GREEN that should have been held for you.
And the planning defect means the single question we ask you — the one you are best placed to answer and
least able to recover from — is currently only partly heard.

**What I need from you: nothing technical.** Every choice above is mine. The one thing worth your attention
is whether slices 5-6 (the planning-path change) should wait until #1195's dispatch features are running,
since both compete for the same overnight windows. My recommendation: **do slices 1-3 and 7 now** (they need
no window at all), and let #1195 have the nights until #1237 has merged.

---

## 8. What I did NOT examine — stated, because an unstated gap is the defect

- `shared/fleet/acceptance.py` outside the ~200 lines cited (~3100 lines total). I read `_choose`,
  `apply_clarification`, `_thread_build_fields`, `_task_build_fields` and `generate_plan`'s **signature
  only** — I did **not** read `generate_plan`'s body, so §2.2's claim that the post-build-signal tail is
  cleanly extractable is **DERIVED** from the #1237 builder's account and the census, not measured by me.
  **The implementer must verify this before committing to slice 6.** It is the design's largest unverified
  assumption.
- `battery.py` entirely (rows 3, and the `_bank_traceability` reference at `:1787-1821` — cited from the
  census, unread by me).
- `fleet-lib.ps1` entirely (rows 9, 14, and #1242's `Test-ShouldMerge` at `:2304-2320` — all cited from the
  censuses, unread by me). Everything I say about PowerShell is DERIVED.
- `green_audit.py` — rows 4, 5, 7, 13 are cited from the census; I verified the *pattern* in
  `security.py`/`layer1.py` but did not open `green_audit.py`.
- `clarify.py`, `static_pregate.py`, `oracle_mutation.py`, the dispatch harness modules, `evals/`, the WinUI
  surface, and the ~35 other `shared/fleet/` modules the census flagged as the richest unswept vein.
- I did not run the standing gate. This branch is documentation-only.

**The census's own caveat is inherited and restated:** the 10/4 split is a classification of its own rows,
not an independent measurement.
