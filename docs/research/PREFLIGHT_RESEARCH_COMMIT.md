---
research-scope: tracker-free
---
# Pre-flight checklist for a research commit

Every commit that adds or changes a measurement record, a probe script, a performance record or the journal fragment that reports
one runs this list. The review of that commit cites this file and states each item's result; a review that does not is a FAIL.
The checks marked LOCK are enforced by `tests/security/test_research_files_carry_no_tracker_numbers.py` (the research-tracker
lock) and by `tests/security/test_no_host_identity_in_tree.py` (the identity lock); the rest are the reviewer's.

## 1. Raw results never enter a repository

- [ ] Every run wrote to `%USERPROFILE%\blarai-research-data\<topic>\`, outside every git tree.
- [ ] Nothing under that folder is staged, copied by hand or attached to a commit. What enters a repository is the sanitiser's
      output only.

## 2. Sanitise at the boundary, by script

- [ ] The bundle was produced by the sanitiser (in `windows-containment-evidence`: `tools/sanitize.py`), never by hand.
- [ ] The sanitiser replaced the host name, the user name, every machine or domain SID (`S-1-5-21-...`), every home path, every
      GUID not on its allowlist, every bare `#` reference of three to five digits (a bare upstream number is rewritten to its
      `owner/repo` form only when the local file lists it, otherwise it is removed), a four-digit number from 1000 to 1999 inside
      a name, and every session token and fixture prefix of four or five digits; its marker file lists counts only. A bare upstream
      number the local file does not list is removed, and the gate cannot see that loss: the re-count in the next item
      (against the raw count and the marker's tracker count) is what catches a lost citation. It does NOT
      rewrite a number of 2000 or more inside a name: that is a hand edit.
- [ ] Every figure the bundle reports was re-counted AFTER sanitising and equals the raw count. A changed count stops the commit.
- [ ] LOCK: `python scripts/scrub_public_identifiers.py --check` exits 0.
- [ ] In the evidence repository: `python tools/leak_gate.py --tree <the sanitised output directory>` and
      `python tools/leak_gate.py --staged` both exit 0 (its pre-commit hook runs the second).

## 3. Names carry no tracker number, no machine, no person

- [ ] Fixtures are `fx-a`, `fx-b`, ...; runs are `run-<YYYYMMDD>-<n>`; branches are `feat/<topic>` or `fix/<topic>`.
- [ ] A script records a tracker reference only in a field the sanitiser blanks.
- [ ] LOCK (research-tracker lock): no file in its scope carries a tracker reference (`#` followed by three to five digits), a
      fixture prefix (`p` or `P` followed by four or five digits and `-` or `_`), a session token (`S` followed by four or five
      digits and `-`), a file or folder NAME carrying a standalone four-digit number that is not the year of a date, or a file that
      has a key-shaped line without parsing as opted in. Key-shaped is: outside a code fence, a line that starts, after
      indentation, with the key word and a colon or with `<!--` and the key word; and inside a leading front matter block, any
      line naming the key word. Prose, inline-code and fenced mentions are not key-shaped; a line that opens with the key words
      and a colon in ordinary text is. A date is a year from 1900 to 2099 followed by a separator and a month
      01 to 12, or an eight-digit YYYYMMDD; a plain year such as 2026 in a name is refused. A
      reference glued to a word is refused; only an allowlisted `owner/repo` slug, a space and an optional `PR` or `issue`
      may precede it. A run from 2000 to 2099 directly before a dot and a digit (`2026.4`), or directly after `ov`
      or `openvino` and before an underscore and a digit (the benchmark harnesses' `ov2026_2_1_0`), is a version and passes; the exemption is narrow in shape and not in range: a tracker number from 2000 to 2099
      written in that shape is not seen.
      Limits: a tracker number from 1900 to 2099 written before a separator and a valid month reads as a date;
      a three-digit tracker number in a name is not seen; a misspelt key, a plural key outside a front
      matter and a TOML (`+++`) front matter leave the file unscoped; a run of five or more digits in a name is not seen; a text file that
      is UTF-16 or has another suffix such as `.mdx` is not read for the opt-in; a short commit hash or an hour-minute stamp
      in a name is refused; a CSS colour or an ordinal written as a hash and three digits is refused (write it
      another way). Scope, by path:
      - `tools/probes/<name>/` (each probe directory; content counts of files already banked are frozen in the lock's baseline and may only fall; a name entry may be added only for a path that already existed at the reference commit)
      - `docs/performance/*.json`
      - `PERFORMANCE_LOG.md` entries opened with the line `<!-- research-scope: tracker-free -->` (the entry runs from that line through its own heading, of any level, and ends at the next heading of the same or a higher level outside a code fence; deeper sub-headings stay inside)
      - any tracked `.md`, `.markdown`, `.txt` or `.rst` file whose front matter carries `research-scope: tracker-free`, journal
        fragments included
      - this file
      Top-level files directly under `tools/probes/` are outside the scope the operator fixed. The lock reads the git index and
      its baseline from the index too; the review of a commit that touches the baseline must also pass the lock's
      `--reference-ref` comparison, which the gate test runs against `main`.
      A new probe directory, performance record, marked entry or marked fragment starts at zero and stays there.

## 4. The purpose stays out

- [ ] No file states who the measurement is for, why it was run beyond its technical question, or where it will be posted.
      The vendor's and the product's names may appear where they are the subject of a technical record; a purpose may not.
- [ ] LOCK: `tests/security/test_public_snapshot_excludes_private_material.py` passes (the excluded-phrase scan).

## 5. Commit messages are technical only

- [ ] The message states the file change and nothing else: no purpose, no audience, no process, no tracker number in a commit
      made inside the evidence repository (its `commit-msg` hook refuses one).

## 6. One branch per measurement, reviewed before merge, merged before snapshot

- [ ] An independent review (author is not the verifier) read the diff and this checklist and recorded its result in a disposition
      record; `python scripts/verify_disposition.py` exits 0.
- [ ] The standing gate is green on the branch before merge and on merged main after.
- [ ] A branch that touches the research-tracker lock's baseline or script lands with `git merge --no-ff`: a fast-forward puts
      every intermediate baseline version on main's first-parent line and the lock's reference check fails on main.
- [ ] The public snapshot runs only through the publisher after a dry run a person reads; every public link pins a commit, never
      `main`.

## 7. Before any public link is pasted

- [ ] One scan of the public file, as published, for the host name, the user name, `DESKTOP-`, `S-1-5-21-`, home paths and tracker
      numbers: zero hits or no post. The scan's command and the file's hash are recorded.

## 8. Tabular export only

- [ ] A dataset upload carries only the tabular export built from the sanitised bundle (the export script's preflight passes);
      nothing raw.

## 9. A result that fails its stated control is not published

- [ ] If the measurement's specification names a FAIL direction and a run met it, nothing about it is committed, pushed or
      uploaded until the specification's private route has run its course.
