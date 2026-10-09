"""The public mirror's GitHub Pages (Jekyll) build must not be fed template-like documents.

Pages renders every file that starts with front matter through Liquid; one document with an
unparseable tag fails the whole build and the site stops updating. The mirror also serves
demo.html, which the README links to, and the snapshot is a tree-for-tree replacement of the
public repo, so the file has to live in this tree.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_LIQUID = re.compile(r"\{%|\{\{")
# Jekyll's front-matter test: optional BOM, then '---' alone on a line.
_FRONT_MATTER = re.compile(rb"\A(\xef\xbb\xbf)?---[ \t]*\r?\n")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True)
    return [p.decode("utf-8") for p in out.stdout.split(b"\0") if p]


def _excluded() -> list[str]:
    """The entries of the top-level `exclude:` list in _config.yml, and nothing else."""
    entries: list[str] = []
    in_block = False
    for line in (REPO_ROOT / "_config.yml").read_text(encoding="utf-8").splitlines():
        if re.match(r"^exclude:\s*$", line):
            in_block = True
        elif in_block and (m := re.match(r"^\s+-\s+(.+?)\s*$", line)):
            entries.append(m.group(1).strip("'\""))
        elif in_block and line.strip() and not line.lstrip().startswith("#"):
            in_block = False
    return entries


def _is_excluded(path: str, excluded: list[str]) -> bool:
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in excluded)


def _would_be_rendered_with_liquid(body: bytes) -> bool:
    return bool(_FRONT_MATTER.match(body)) and bool(_LIQUID.search(body.decode("utf-8", "replace")))


def _offenders(excluded: list[str]) -> list[str]:
    found = []
    for p in _tracked():
        if _is_excluded(p, excluded):
            continue
        f = REPO_ROOT / p
        if not f.is_file():
            continue
        with f.open("rb") as fh:
            if not _FRONT_MATTER.match(fh.read(8)):
                continue
        if _would_be_rendered_with_liquid(f.read_bytes()):
            found.append(p)
    return found


def test_the_demo_page_the_readme_links_to_is_in_the_tree() -> None:
    assert "demo.html" in _tracked(), "README links to the Pages demo player; a snapshot without it deletes it"
    assert "demo.html" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_no_rendered_document_carries_liquid_tags() -> None:
    excluded = _excluded()
    assert excluded, "vacuous: _config.yml excludes nothing"
    assert all((REPO_ROOT / e).exists() for e in excluded), f"_config.yml excludes a path that does not exist: {excluded}"
    offenders = _offenders(excluded)
    assert offenders == [], f"Jekyll would render these through Liquid and may fail the Pages build: {offenders}"


def test_the_exclude_is_what_keeps_the_known_offenders_out() -> None:
    """Toggle-test: with the exclude list emptied the scan finds the documents that failed the build."""
    assert _offenders([]), "no document trips the scan with nothing excluded; the scan or the premise is blind"


def test_the_detector_fires_on_the_failing_shape_and_on_a_bom() -> None:
    body = b"---\ntitle: t\n---\n{% if a is defined and a is false %}x{% endif %}\n"
    assert _would_be_rendered_with_liquid(body)
    assert _would_be_rendered_with_liquid(b"\xef\xbb\xbf" + body)
    assert not _would_be_rendered_with_liquid(body.replace(b"---", b"==="))
    assert not _would_be_rendered_with_liquid(b"---\ntitle: t\n---\nplain text\n")
