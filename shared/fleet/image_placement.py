"""Deterministic media-placement grader for a delivered web product — DoD capability 18.

**Why this exists (the load-bearing rationale).** On 2026-08-08 the Lead Architect opened a
pottery-shop site the coding fleet had built and said two things::

    "I see the same images were used over and over."
    "I see that descriptions of the products don't match the image."

Both are true on disk. That delivery listed SIX products and shipped TWO pictures: three
mugs all rendered ``assets/mug.png``, and the three bowls — including one whose own
description reads "set of three rustic bowls" — rendered ``assets/hero.png``, the
potter-at-the-wheel banner photograph, because no bowl image had been generated. The next
night's build improved to one image per CATEGORY, which is a gallery where ``Classic Mug``,
``Travel Mug`` and ``Tea Cup Set`` are three products wearing one photograph.

Capability 18 ("the product's media content is generated, placed and graded") reads UNKNOWN
because only the GENERATION half exists. The images themselves are good — that is not the
defect. **Nothing in the pipeline asks whether the media a page implies actually exists, or
whether one asset is doing the work of six.** This module is the missing placement grader:
no model, no network, no browser, no pixels — it reads the data source the page renders from
and the assets the tree ships, and reports the arithmetic between them.

**Sibling modules.** :mod:`shared.fleet.link_lint` (capability 15) is the direct sibling and
the model for this one: same philosophy, same report shape, same honesty rules — read its
header first. :mod:`shared.fleet.layout_lint` is the older sibling aimed at WinUI XAML. All
three are deterministic, precision-first, and report rather than guess.

**What this closes that** :mod:`link_lint` **structurally cannot.** A gallery renders its
images from a template (``<img src="${piece.image}">``). ``link_lint`` is required to count
that as *undecidable* — it is a runtime value — so an item pointing at an image that does not
exist is invisible to it. Here the same reference IS decidable, because the value comes from
the data source rather than from the markup. That is why ``item-image-missing`` lives in this
module and not that one.

**The rules** (precision-first — a false positive nags the coder into "fixing" correct
markup, so every rule is guarded to fire only on a real defect):

  repeated-item-image   One asset is the declared image of REPEAT_THRESHOLD (3) or more
                        distinct items. Pure counting, no name inference. HIGH.
  item-image-missing    An item's declared image names no file anywhere in the delivered
                        repository. The gallery renders a broken picture. HIGH.
  item-image-diversity  Diffuse duplication: four or more items, half or fewer distinct
                        images, and no single asset reached the repeat threshold (many
                        assets each used twice). LOW — reported only when
                        ``repeated-item-image`` found nothing, so one defect is never
                        counted twice.
  decorative-as-item    An item's image is page furniture by name (hero / logo / banner /
                        background / placeholder). Inferred from the FILE NAME. LOW.
  subject-mismatch      The item's declared subject and its asset's declared subject are
                        disjoint, AND an asset matching the item's subject exists in the
                        tree — i.e. the right picture was available and the wrong one was
                        used. Inferred from NAMES, never from the image. LOW.
  item-without-image    A collection where some items declare an image and this one does
                        not. LOW.
  unreferenced-asset    An image in the served tree that nothing in the repository names.
                        A finding about the PIPELINE, not the page: the run that prompted
                        this module generated ``icon-mug.png`` and ``icon-bowl.png`` at
                        roughly 76 s of GPU time each and referenced neither. LOW.
  unreadable            A data source that could not be read or parsed. LOW, fail-soft.

**Why the repeat threshold is 3 and not 2.** Two items sharing an asset is a coin flip:
colour variants, a boxed pair, a deliberate series shot, a "collection" and its lead piece.
Three is a pattern, and a pattern in generated content is a pipeline defect rather than a
coincidence — it means the generator produced fewer subjects than the data source declares
and the placer reused what it had. Three is also the point at which the operator's own
complaint becomes visible without counting: "the same images were used over and over" was
written about a page where one asset appeared three times. Setting the threshold at 2 would
buy recall with precision, which is the wrong trade for a signal a coder acts on; the diffuse
case it would catch is still reported, at LOW, by ``item-image-diversity``.

**Why a shared logo or hero banner is never flagged, structurally.** The repeat rule counts
only assets an ITEM DECLARES in the data source. A logo in the navigation of five pages, a
hero banner on the home page, a background in the stylesheet — none of them is an item image,
so none of them can reach the counter. That is a structural guard rather than a threshold
tuned to dodge them, which is why it cannot rot. The same asset used BOTH as page furniture
AND as a product photograph — the operator's actual bowls — is still caught, because there it
is declared by items.

**What this module deliberately does NOT do**, recorded because an unnamed limit reads as a
clean result (capability 7): it never opens an image. Every subject judgement is inferred from
file names and data fields, so a mug photographed and saved as ``bowl.png`` reads here as a
bowl, and two identical pictures saved under two names read as two subjects. It does not
render the page, evaluate JavaScript, or check that an image is the right size, orientation or
quality. Everything it could not decide is counted and named in ``not_measured``.

**Honesty contract (the reason this module exists at all).** A site with NO media and a site
whose media is all correctly placed must produce DIFFERENT reports. When nothing could be
graded the report says ``checked: false``, gives a plain-language reason, and publishes NO
counts — a zero that came from an unrun check must never be able to wear a clean check's
clothes. Each of the two dimensions (item placement, asset usage) carries its own
``checked``/``reason`` pair for the same reason, and counts are published only for a dimension
that actually ran.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from shared.fleet.link_lint import detect_served_root

SEVERITY_HIGH = "high"
SEVERITY_LOW = "low"

# A finding is HARD (would force a FIX iteration) iff its severity is HIGH. Whether a caller
# ACTS on `hard` is the caller's decision — the wiring in swap_ops deliberately does not.
_HARD_SEVERITIES = {SEVERITY_HIGH}

#: An asset that is the declared image of this many distinct items is a repeat. See the
#: module docstring for why 3 rather than 2 — it is the module's central judgement call.
REPEAT_THRESHOLD = 3

#: The diffuse-duplication rule needs enough items for a ratio to mean anything, and fires
#: only when half or fewer of the items got their own picture.
_DIVERSITY_MIN_ITEMS = 4
_DIVERSITY_MAX_RATIO = 0.5

#: Record keys that carry an item's picture, most conventional first. The first key whose
#: values actually look like image paths wins, so a record carrying both `image` and `thumb`
#: is graded on the one the gallery renders.
_ITEM_IMAGE_KEYS: tuple[str, ...] = (
    "image", "imageurl", "image_url", "img", "photo", "picture",
    "cover", "thumbnail", "thumb", "src",
)

#: Record keys that declare what an item IS. Deliberately excludes `description`: free prose
#: mentions neighbouring subjects ("perfect beside your morning mug") and would make a
#: name-based subject test read matches that are not there.
_ITEM_SUBJECT_KEYS: tuple[str, ...] = (
    "name", "title", "label", "category", "categories", "type", "kind", "collection", "tags",
)

#: File-name stems that mark an asset as page furniture rather than a subject photograph.
_DECORATIVE_TOKENS = frozenset({
    "hero", "banner", "logo", "background", "bg", "splash", "cover", "placeholder",
    "header", "footer", "divider", "texture", "watermark", "wallpaper", "masthead",
})

#: Tokens that carry no subject on either side of a name comparison — packaging words, size
#: qualifiers and format noise. Dropped before any subject is inferred.
_NOISE_TOKENS = frozenset({
    "img", "image", "images", "photo", "photos", "pic", "pics", "picture", "pictures",
    "asset", "assets", "media", "icon", "icons", "small", "medium", "large", "thumb",
    "thumbnail", "full", "main", "default", "final", "new", "old", "set", "the", "and",
    "with", "for", "our", "png", "jpg", "jpeg", "webp", "svg",
})

#: Extensions this module treats as an image asset.
_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".bmp", ".ico",
})

#: Suffixes worth reading when hunting for a reference to an asset. Deliberately wide: a
#: name found ANYWHERE in the repository counts as a reference, because the cost of a false
#: "nothing uses this" is a coder deleting a file the site needs.
_TEXT_SUFFIXES = frozenset({
    ".html", ".htm", ".xhtml", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue",
    ".css", ".scss", ".sass", ".less", ".json", ".md", ".txt", ".svg", ".xml", ".yml",
    ".yaml", ".py", ".cs", ".php", ".rb", ".hbs", ".ejs", ".njk", ".liquid",
})

#: Directory names no delivered site serves.
#:
#: ``testing_output`` and its spellings hold screenshots from a testing session, not site
#: media. Counting them as unplaced assets reported six "wasted" images in `Hello-World`
#: that were nobody's mistake — the first population sweep, 2026-08-08, found them.
_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "coverage", ".cache", "dist-info",
    "testing_output", "testing-output", "test_output", "test-output", "screenshots",
})

#: A directory the OPERATOR fills, not the pipeline. Nothing under one may ever be graded
#: as generated media.
#:
#: **Why this is structural rather than a name guess.** The project scaffold writes a
#: ``README.txt`` into its intake folder reading *"Put photos, documents, and other
#: material for the build in here; screenshots to emulate go in the reference folder."*
#: That file is the marker, so the exclusion rests on a thing the scaffold actually wrote
#: rather than on a directory being called `assets` — plenty of generated media lives in a
#: directory called `assets`, and excluding by name would blind the rule to the real case.
#:
#: The first population sweep (2026-08-08) counted 29 of the operator's OWN family
#: photographs in `recipe-site` as pipeline waste — five-sixths of the headline number, and
#: an instrument that tells a person their own uploads were a machine's mistake is worse
#: than no instrument at all. That is the false-positive class this module's own docstring
#: warns about, committed by this module, and found only by opening the directory.
_INTAKE_MARKER_NAMES = ("README.txt", "readme.txt")
_INTAKE_MARKER_PHRASES = (
    "put photos, documents",
    "material for the build",
    "screenshots to emulate",
    "pictures to emulate",
)

#: JSON files that are configuration, never a content collection. Excluded by name so a
#: dependency list can never be mistaken for a product catalogue.
_CONFIG_JSON_NAMES = frozenset({
    "package.json", "package-lock.json", "tsconfig.json", "jsconfig.json", "composer.json",
    "manifest.json", "site.webmanifest", "bower.json", "angular.json", "nx.json",
    "lerna.json", ".eslintrc.json", ".babelrc.json", "renovate.json", "vercel.json",
    "netlify.json", "now.json", "jest.config.json", "launchSettings.json",
})

#: Assets a browser or platform fetches by convention with no markup naming them. Exempt
#: from the unreferenced rule — a favicon nobody links is doing its job.
_IMPLICITLY_REFERENCED_PREFIXES = ("favicon", "apple-touch-icon", "android-chrome", "mstile")

#: Split a name into words on any non-alphanumeric run, and on digit groups.
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+|(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])")

#: Largest text file worth scanning for a reference. Anything bigger is generated output,
#: and reading it would cost more than the finding is worth.
_MAX_TEXT_BYTES = 4_000_000

#: Depth limit for the walk that finds collections inside a JSON document.
_MAX_JSON_DEPTH = 4


@dataclass(frozen=True)
class Finding:
    """One deterministic media-placement defect.

    Attributes:
        rule: stable rule id (repeated-item-image / subject-mismatch / ...).
        severity: ``high`` (structural, decided by counting) or ``low`` (advisory, or
            inferred from names rather than from the picture).
        message: actionable, human-readable description of what to fix.
        reference: the asset the finding is about ("" when there is none).
        item: the item's display name ("" for a finding about an asset, not an item).
        file: repository-relative path of the data source or asset it came from.
    """

    rule: str
    severity: str
    message: str
    reference: str
    item: str = ""
    file: str = ""


@dataclass(frozen=True)
class Item:
    """One record from a content collection, reduced to what placement grading needs.

    Attributes:
        label: the item's display name, for messages the operator reads.
        image: the image path exactly as the data source declares it ("" when absent).
        subjects: normalised subject tokens drawn from the item's name/category fields.
        source: repository-relative path of the data source it came from.
    """

    label: str
    image: str
    subjects: frozenset[str]
    source: str


@dataclass(frozen=True)
class Collection:
    """One array of items found in one data source.

    Attributes:
        source: repository-relative path of the file.
        path: where inside the document the array sat ("" for a top-level array).
        field: the record key that carried the image path.
        items: the records, in document order.
    """

    source: str
    path: str
    field: str
    items: tuple[Item, ...]


# ---------------------------------------------------------------------------
# Name analysis — every subject judgement in this module comes from here
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    """Subject-bearing words in ``text``, lower-cased and stripped of noise.

    Tokens shorter than three characters are dropped: they are almost always sizes, indices
    or articles, and a two-letter match between a product name and a file name is not
    evidence of anything.
    """
    out: set[str] = set()
    for raw in _TOKEN_SPLIT_RE.split(text.lower()):
        if len(raw) >= 3 and not raw.isdigit() and raw not in _NOISE_TOKENS:
            out.add(raw)
    return out


def _subjects_match(left: str, right: str) -> bool:
    """True when two subject tokens plausibly name the same thing.

    A prefix match rather than an equality test, which is how ``mug``/``mugs`` and
    ``vase``/``vases`` are reconciled without a stemmer that has to be right about English.
    The comparison is deliberately LENIENT: every rule that uses it fires on the ABSENCE of a
    match, so leniency costs recall and buys precision — the correct direction for a
    name-based heuristic that a coder will act on.
    """
    return left == right or left.startswith(right) or right.startswith(left)


def _any_subject_matches(left: Iterable[str], right: Iterable[str]) -> bool:
    """True when any token on the left plausibly names any token on the right."""
    right_list = list(right)
    return any(_subjects_match(a, b) for a in left for b in right_list)


def _asset_subjects(asset_path: str, vocabulary: Iterable[str]) -> set[str]:
    """The subjects an asset's FILE NAME declares, restricted to the collection's vocabulary.

    Restricting to words the data source itself uses is what keeps this from inventing
    subjects: ``hero.png`` in a pottery catalogue declares nothing, because no item is a
    "hero". Only a file name that speaks the catalogue's own language is allowed to make a
    claim about what it depicts.
    """
    stem_tokens = _tokens(Path(asset_path).stem)
    vocab = list(vocabulary)
    return {token for token in stem_tokens if _any_subject_matches([token], vocab)}


def _is_decorative(asset_path: str) -> bool:
    """True when an asset's file name marks it as page furniture and nothing else.

    Requires EVERY surviving token to be decorative, so ``hero.png`` and ``hero-banner.png``
    qualify while ``mug-hero.png`` does not — the latter names a subject, and a subject
    outranks a layout word. Tokenises raw rather than through :func:`_tokens`, which drops
    words under three characters: ``bg.png`` is the single most conventional decorative name
    there is, and the general filter would silently make it invisible here.
    """
    tokens = [
        token for token in _TOKEN_SPLIT_RE.split(Path(asset_path).stem.lower())
        if token and not token.isdigit()
    ]
    return bool(tokens) and all(token in _DECORATIVE_TOKENS for token in tokens)


# ---------------------------------------------------------------------------
# Data-source discovery
# ---------------------------------------------------------------------------


def _iter_repo_files(repo: Path) -> Iterable[Path]:
    """Every file in the repository, skipping directories no delivered site serves."""
    for path in sorted(repo.rglob("*")):
        if path.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def _rel(path: Path, base: Path) -> str:
    """``path`` relative to ``base`` with forward slashes, or its name if unrelated."""
    try:
        return str(path.relative_to(base)).replace("\\", "/")
    except ValueError:
        return path.name


def _looks_like_image(value: object) -> bool:
    """True when a field value is a string naming an image file."""
    return isinstance(value, str) and Path(value.split("?", 1)[0].strip()).suffix.lower() in _IMAGE_EXTENSIONS


def _candidate_arrays(payload: Any, path: str = "", depth: int = 0) -> Iterable[tuple[str, list[dict]]]:
    """Every array-of-objects inside a parsed JSON document, with where it sat.

    Walks nested containers because a catalogue is as often ``{"pieces": [...]}`` as it is a
    bare top-level array, and a site with several collections (products, testimonials, team)
    should have all of them graded rather than the first one found.
    """
    if depth > _MAX_JSON_DEPTH:
        return
    if isinstance(payload, list):
        records = [entry for entry in payload if isinstance(entry, dict)]
        if len(records) >= 2:
            yield path, records
        for index, entry in enumerate(payload[:50]):
            if isinstance(entry, (dict, list)):
                yield from _candidate_arrays(entry, f"{path}[{index}]", depth + 1)
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                yield from _candidate_arrays(value, f"{path}.{key}" if path else str(key), depth + 1)


def _image_field(records: list[dict]) -> str:
    """The record key that carries the item image, or "" when this is not a media collection.

    Requires at least two records to carry a value that actually names an image file. One is
    not a collection and could be any configuration blob; the extension requirement is what
    stops a ``src`` field full of module paths from being mistaken for artwork.
    """
    lowered = [{str(k).lower(): v for k, v in record.items()} for record in records]
    for key in _ITEM_IMAGE_KEYS:
        hits = sum(1 for record in lowered if _looks_like_image(record.get(key)))
        if hits >= 2:
            return key
    return ""


def _item_label(record: dict, index: int) -> str:
    """A human-readable name for a record, for the messages the operator reads."""
    lowered = {str(k).lower(): v for k, v in record.items()}
    for key in ("name", "title", "label", "id", "slug"):
        value = lowered.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return f"item #{index + 1}"


def _item_subjects(record: dict) -> frozenset[str]:
    """Normalised subject tokens for one record, drawn from its name/category fields."""
    lowered = {str(k).lower(): v for k, v in record.items()}
    out: set[str] = set()
    for key in _ITEM_SUBJECT_KEYS:
        value = lowered.get(key)
        if isinstance(value, str):
            out |= _tokens(value)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    out |= _tokens(entry)
    return frozenset(out)


def find_collections(repo: str | Path) -> tuple[list[Collection], list[Finding]]:
    """Every item collection in the repository, plus fail-soft findings for what would not parse.

    Data sources are hunted across the WHOLE repository rather than under the served root:
    the delivery that prompted this module keeps its catalogue in ``data/pieces.json``, one
    level ABOVE the ``public/`` directory the server mounts. A grader that looked only where
    the files are served would have found nothing to grade and reported a clean site.
    """
    base = Path(repo)
    collections: list[Collection] = []
    findings: list[Finding] = []

    for path in _iter_repo_files(base):
        if path.suffix.lower() != ".json" or path.name in _CONFIG_JSON_NAMES:
            continue
        rel = _rel(path, base)
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            findings.append(
                Finding(
                    rule="unreadable",
                    severity=SEVERITY_LOW,
                    message=f"Could not read or parse {rel}: {type(exc).__name__}. Nothing in it was graded.",
                    reference="",
                    file=rel,
                )
            )
            continue

        for where, records in _candidate_arrays(payload):
            field_name = _image_field(records)
            if not field_name:
                continue
            items = tuple(
                Item(
                    label=_item_label(record, index),
                    image=str({str(k).lower(): v for k, v in record.items()}.get(field_name) or "").strip(),
                    subjects=_item_subjects(record),
                    source=rel,
                )
                for index, record in enumerate(records)
            )
            collections.append(Collection(source=rel, path=where, field=field_name, items=items))

    return collections, findings


# ---------------------------------------------------------------------------
# Asset discovery and resolution
# ---------------------------------------------------------------------------


def _normalise_asset(raw: str) -> str:
    """A comparable key for an image path: query stripped, separators and case normalised."""
    path = raw.split("#", 1)[0].split("?", 1)[0].strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/").lower()


def _repo_file_names(repo: Path) -> set[str]:
    """Every file name in the repository, lower-cased. Built once, consulted on a miss."""
    return {path.name.lower() for path in _iter_repo_files(repo)}


def _asset_exists(
    repo: Path,
    served_root: Path,
    rel: str,
    names: Callable[[], set[str]] | None = None,
) -> bool:
    """Whether a declared image is anywhere in the delivery.

    Tries the served root, then the repository root, then a name search across the whole
    repository. That last fallback is the precision guard for ``item-image-missing``: a data
    source sitting outside the served root may express its paths against a base this module
    cannot know, so the rule fires only when the file is absent EVERYWHERE — never merely
    because the base was guessed wrong. ``names`` lets a caller grading many items pay for
    that repository walk at most once, and only when some item actually misses.
    """
    cleaned = _normalise_asset(rel)
    if not cleaned:
        return False
    for base in (served_root, repo):
        try:
            if (base / cleaned).is_file():
                return True
        except OSError:
            continue
    index = _repo_file_names(repo) if names is None else names()
    return Path(cleaned).name in index


def _is_operator_intake_dir(directory: Path) -> bool:
    """True when this directory is one the OPERATOR fills, per its own marker file.

    Reads the scaffold's own ``README.txt`` rather than matching a directory name: media
    generated by the pipeline commonly lives in a directory called ``assets`` too, so a
    name test would either miss real waste or flag the operator's uploads. The marker is a
    thing the scaffold actually wrote, which makes the exclusion checkable.
    """
    for marker in _INTAKE_MARKER_NAMES:
        path = directory / marker
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(phrase in text for phrase in _INTAKE_MARKER_PHRASES):
            return True
    return False


def _intake_roots(repo: Path) -> list[Path]:
    """Every operator-intake directory in the repository, marker-identified.

    Cost, measured 2026-08-08 on the real B9 delivery: 13 ms over 284 entries, inside a
    53 ms whole-grade. ``rglob`` descends into a skipped directory before the filter drops
    it, so a repository carrying ``node_modules`` would walk it — matching
    :func:`_iter_repo_files`, which has done the same since it was written. Left as-is
    deliberately: the scaffold's web projects are zero-dependency by design (B9 has no
    ``node_modules``), this grader is advisory and fail-soft, and even a hundredfold
    regression is seconds against a build measured in tens of minutes. Prune during the
    walk if a dependency-heavy card ever lands.
    """
    roots: list[Path] = []
    for directory in [repo, *(p for p in repo.rglob("*") if p.is_dir())]:
        if any(part in _SKIP_DIRS for part in directory.parts):
            continue
        if _is_operator_intake_dir(directory):
            roots.append(directory)
    return roots


def _under_any(path: Path, roots: list[Path]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _image_assets(served_root: Path, intake_roots: list[Path] | None = None) -> list[Path]:
    """Every image file in the served tree, in a stable order.

    Anything under an operator-intake directory is excluded outright: it is HIS material,
    it was not generated, and no rule in this module has any business grading it.
    """
    roots = intake_roots or []
    return [
        path
        for path in _iter_repo_files(served_root)
        if path.suffix.lower() in _IMAGE_EXTENSIONS and not _under_any(path, roots)
    ]


def _unreferenced_assets(repo: Path, assets: list[Path]) -> tuple[list[Path], list[str], int]:
    """Assets whose file name appears in no text file in the repository.

    Matching is by BASENAME across every readable text file, tests and documentation
    included. That is deliberately the loosest possible test: this rule reports wasted
    generation, and the cost of being wrong is a coder deleting an image the site needs.
    Returns the orphans, the files that could not be read (a skipped file is a place a
    reference could have been hiding) and how many assets were exempted by convention —
    all three, because an exempted asset was not verified and must not be counted as though
    it had been.
    """
    wanted = {path.name.lower(): path for path in assets}
    exempt = 0
    for path in assets:
        if path.stem.lower().startswith(_IMPLICITLY_REFERENCED_PREFIXES):
            if wanted.pop(path.name.lower(), None) is not None:
                exempt += 1
    skipped: list[str] = []
    if not wanted:
        return [], skipped, exempt

    for path in _iter_repo_files(repo):
        if not wanted:
            break
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _MAX_TEXT_BYTES:
                skipped.append(_rel(path, repo))
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            skipped.append(_rel(path, repo))
            continue
        for name in [n for n in wanted if n in text]:
            wanted.pop(name, None)

    return sorted(wanted.values()), skipped, exempt


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def _grade_repeats(items: list[Item]) -> list[Finding]:
    """``repeated-item-image`` — one asset doing the work of several products.

    Counts only assets an ITEM declares, which is why a logo shared across every page cannot
    reach this rule. See the module docstring for the threshold's justification.
    """
    users: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        if item.image:
            users[_normalise_asset(item.image)].append(item)

    findings: list[Finding] = []
    for asset, sharers in sorted(users.items()):
        if len(sharers) < REPEAT_THRESHOLD:
            continue
        names = ", ".join(f"'{item.label}'" for item in sharers[:6])
        extra = f" and {len(sharers) - 6} more" if len(sharers) > 6 else ""
        findings.append(
            Finding(
                rule="repeated-item-image",
                severity=SEVERITY_HIGH,
                message=(
                    f"{len(sharers)} different products all show the same picture "
                    f"('{sharers[0].image}'): {names}{extra}. A visitor sees the same photograph "
                    f"repeated down the page, so the products do not look like different products."
                ),
                reference=sharers[0].image,
                item=sharers[0].label,
                file=sharers[0].source,
            )
        )
    return findings


def _grade_diversity(items: list[Item]) -> list[Finding]:
    """``item-image-diversity`` — the diffuse case the repeat rule is too strict to see."""
    with_image = [item for item in items if item.image]
    if len(with_image) < _DIVERSITY_MIN_ITEMS:
        return []
    distinct = {_normalise_asset(item.image) for item in with_image}
    if len(distinct) > len(with_image) * _DIVERSITY_MAX_RATIO:
        return []
    return [
        Finding(
            rule="item-image-diversity",
            severity=SEVERITY_LOW,
            message=(
                f"{len(with_image)} products share only {len(distinct)} different pictures between "
                f"them. No single picture is repeated enough to be certain this is wrong, but the "
                f"gallery is mostly duplicates."
            ),
            reference="",
            item="",
            file=with_image[0].source,
        )
    ]


def _grade_subjects(items: list[Item], available: dict[str, set[str]]) -> list[Finding]:
    """``decorative-as-item`` and ``subject-mismatch`` — both inferred from NAMES.

    ``available`` maps each asset in the delivered tree to the subjects its file name
    declares. The mismatch rule fires only when a BETTER asset was on hand: an item that is a
    bowl, rendering a mug, in a tree that ships a bowl picture. Without that clause the rule
    would fire on every site whose art has not been generated yet, which is a planning
    problem and not a placement one.
    """
    findings: list[Finding] = []
    for item in items:
        if not item.image:
            continue
        if _is_decorative(item.image):
            findings.append(
                Finding(
                    rule="decorative-as-item",
                    severity=SEVERITY_LOW,
                    message=(
                        f"'{item.label}' is shown using '{item.image}', which is named like a page "
                        f"decoration (a banner, logo or background) rather than a picture of the "
                        f"product. Inferred from the file name - this check never opens the image."
                    ),
                    reference=item.image,
                    item=item.label,
                    file=item.source,
                )
            )
            continue

        declared = available.get(_normalise_asset(item.image), set())
        if not declared or not item.subjects:
            continue
        if _any_subject_matches(item.subjects, declared):
            continue
        better = sorted(
            asset
            for asset, subjects in available.items()
            if subjects and _any_subject_matches(item.subjects, subjects)
        )
        if not better:
            continue
        findings.append(
            Finding(
                rule="subject-mismatch",
                severity=SEVERITY_LOW,
                message=(
                    f"'{item.label}' is shown using '{item.image}', whose name says it is a "
                    f"{'/'.join(sorted(declared))}. The delivered site also contains '{better[0]}', "
                    f"which matches what this product is. Inferred from names only - this check "
                    f"never opens the image."
                ),
                reference=item.image,
                item=item.label,
                file=item.source,
            )
        )
    return findings


def _grade_existence(items: list[Item], repo: Path, served_root: Path) -> tuple[list[Finding], int]:
    """``item-image-missing`` and ``item-without-image``. Returns the findings and the miss count.

    This is the rule :mod:`link_lint` structurally cannot have: the gallery's markup says
    ``src="${piece.image}"``, which is undecidable there and fully decidable here.
    """
    findings: list[Finding] = []
    missing = 0
    # The repository name index is the expensive half of the fallback, so it is built at most
    # once per grading pass, and only once an item's image has already missed both bases.
    cache: dict[str, set[str]] = {}

    def names() -> set[str]:
        if "names" not in cache:
            cache["names"] = _repo_file_names(repo)
        return cache["names"]

    for item in items:
        if not item.image:
            findings.append(
                Finding(
                    rule="item-without-image",
                    severity=SEVERITY_LOW,
                    message=(
                        f"'{item.label}' has no picture at all, while other products in the same "
                        f"list do. It will render with an empty space where their photographs are."
                    ),
                    reference="",
                    item=item.label,
                    file=item.source,
                )
            )
            continue
        if not _asset_exists(repo, served_root, item.image, names):
            missing += 1
            findings.append(
                Finding(
                    rule="item-image-missing",
                    severity=SEVERITY_HIGH,
                    message=(
                        f"'{item.label}' points at '{item.image}', which is not in the delivered "
                        f"site. Its picture will be a broken image on the page."
                    ),
                    reference=item.image,
                    item=item.label,
                    file=item.source,
                )
            )
    return findings, missing


# ---------------------------------------------------------------------------
# The grader
# ---------------------------------------------------------------------------


def _absent(reason: str, served_root: str, root_reason: str, findings: list[Finding],
            not_measured: list[str], *, nothing_to_grade: bool) -> dict:
    """The report shape for a grading pass that did not happen.

    Publishes NO counts. A zero produced by a check that never ran must not be able to look
    like a zero produced by a clean one — that confusion is #1342, the defect this whole arc
    exists to retire, and an instrument written against it must not commit it.
    """
    return {
        "schema": "image-placement/v1",
        "checked": False,
        "nothing_to_grade": nothing_to_grade,
        "reason": reason,
        "served_root": served_root,
        "served_root_reason": root_reason,
        "data_sources": [],
        "collections": [],
        "findings": [asdict(f) for f in findings],
        "hard": has_hard_findings(findings),
        "checks": {
            "item_placement": {"checked": False, "reason": reason},
            "asset_usage": {"checked": False, "reason": reason},
        },
        "counts": {},
        "not_measured": not_measured,
    }


def grade_site(site_dir: str | Path, served_root: str | Path | None = None) -> dict:
    """Grade a delivered site's media PLACEMENT. Returns the report dict.

    Two dimensions are graded independently, and each says for itself whether it ran:

    * **item placement** — needs a data source with per-item images. Absent one, this
      dimension reports ``checked: false`` with a reason and publishes no counts, even when
      the other dimension ran perfectly well.
    * **asset usage** — needs image files in the served tree. Same contract.

    Top-level ``checked`` is true when EITHER dimension ran. ``nothing_to_grade`` separates
    the two ways it can be false: a site that carries no media at all (normal, nothing to
    say) from a site whose grading could not be performed (a missing directory, an
    unreadable tree). A caller that reads only ``hard`` gets a correct answer; a caller that
    reads ``checks`` and ``not_measured`` gets an honest one.
    """
    repo = Path(site_dir)
    if not repo.is_dir():
        return _absent(
            f"site directory does not exist: {repo}",
            "", "", [],
            ["nothing was graded: the site directory does not exist"],
            nothing_to_grade=False,
        )

    if served_root is None:
        root, root_reason = detect_served_root(repo)
    else:
        root, root_reason = Path(served_root), "explicitly supplied by the caller"

    collections, findings = find_collections(repo)
    # Identified BEFORE anything is graded: the operator's own uploads must never reach a
    # rule, not merely be forgiven by one.
    intake_roots = _intake_roots(repo)
    assets = _image_assets(root, intake_roots) if root.is_dir() else []

    items: list[Item] = [item for collection in collections for item in collection.items]
    item_ran = bool(items)
    asset_ran = bool(assets)

    if not item_ran and not asset_ran:
        reason = (
            "this site declares no media: no image files under the served root "
            f"({root}) and no data file listing items with pictures"
        )
        return _absent(
            reason, str(root), root_reason, findings,
            [(
                "NOTHING was graded: the delivery contains no images and no item data. "
                "This is not a clean result, it is an absent one"
            )],
            nothing_to_grade=True,
        )

    counts: dict[str, int] = {}
    checks: dict[str, dict[str, object]] = {}
    not_measured: list[str] = []

    if item_ran:
        missing_total = 0
        worst = 0
        # Graded one COLLECTION at a time rather than over the merged list. A repository that
        # ships its catalogue twice — `data/pieces.json` and a copy under the served root, a
        # shape these scaffolds produce — would otherwise double every item and report a
        # repeat on a site where each product has its own picture. The defect this rule names
        # is repetition WITHIN a list, so within a list is where it is counted.
        for collection in collections:
            group = list(collection.items)
            # The vocabulary is this catalogue's own words. An asset may only claim a subject
            # the data source itself uses, which is what stops `hero.png` from declaring that
            # it depicts a hero.
            vocabulary = {token for item in group for token in item.subjects}
            available: dict[str, set[str]] = {
                _normalise_asset(_rel(path, root)): _asset_subjects(path.name, vocabulary)
                for path in assets
            }
            repeats = _grade_repeats(group)
            findings += repeats
            findings += _grade_subjects(group, available)
            existence, missing = _grade_existence(group, repo, root)
            findings += existence
            if not repeats:
                findings += _grade_diversity(group)

            missing_total += missing
            usage: dict[str, int] = defaultdict(int)
            for item in group:
                if item.image:
                    usage[_normalise_asset(item.image)] += 1
            worst = max(worst, max(usage.values(), default=0))

        with_image = [item for item in items if item.image]
        counts |= {
            "items": len(items),
            "items_with_image": len(with_image),
            "items_without_image": len(items) - len(with_image),
            "distinct_item_images": len({_normalise_asset(i.image) for i in with_image}),
            "max_items_per_image": worst,
            "items_with_missing_image": missing_total,
        }
        checks["item_placement"] = {"checked": True, "reason": ""}
    else:
        reason = "no data file listing items with pictures was found, so nothing declares what each picture is FOR"
        checks["item_placement"] = {"checked": False, "reason": reason}
        not_measured.insert(0, f"item placement was NOT graded: {reason}")

    if asset_ran:
        orphans, skipped, exempt = _unreferenced_assets(repo, assets)
        for path in orphans:
            rel = _rel(path, repo)
            findings.append(
                Finding(
                    rule="unreferenced-asset",
                    severity=SEVERITY_LOW,
                    message=(
                        f"'{rel}' was produced but nothing in the delivery uses it. Generating a "
                        f"picture no page shows is time spent for nothing."
                    ),
                    reference=rel,
                    file=rel,
                )
            )
        intake_images = sum(
            1
            for path in _iter_repo_files(repo)
            if path.suffix.lower() in _IMAGE_EXTENSIONS and _under_any(path, intake_roots)
        )
        counts |= {
            "image_assets": len(assets),
            "unreferenced_assets": len(orphans),
            "referenced_assets": len(assets) - len(orphans) - exempt,
            "exempt_assets": exempt,
            "operator_intake_images": intake_images,
        }
        checks["asset_usage"] = {"checked": True, "reason": ""}
        if intake_images:
            # Named, not silently dropped. The reader must be able to tell "we examined
            # nothing there" from "there was nothing there" — and the operator should be
            # able to see his own material was recognised as his rather than overlooked.
            not_measured.append(
                f"{intake_images} image(s) sit in a folder the OPERATOR fills (its own "
                f"README says so) and were EXCLUDED from every rule - they are his material, "
                f"not generated output, and nothing here grades them"
            )
        if skipped:
            not_measured.append(
                f"{len(skipped)} file(s) could not be read while hunting for references, so an "
                f"'unused' picture may simply be referenced somewhere unreadable"
            )
        if exempt:
            not_measured.append(
                f"{exempt} asset(s) named as a favicon or platform icon were EXEMPTED from the "
                f"unused check rather than verified - the browser fetches them by convention"
            )
    else:
        reason = f"the served root ({root}) contains no image files"
        checks["asset_usage"] = {"checked": False, "reason": reason}
        not_measured.insert(0, f"asset usage was NOT graded: {reason}")

    not_measured += [
        (
            "no image is ever opened: every judgement about WHAT a picture shows is inferred "
            "from its file name, so a mug saved as 'bowl.png' reads here as a bowl"
        ),
        "two assets with different names may be the same picture - duplicate CONTENT is invisible",
        "images referenced only from code this check cannot evaluate are not counted as used",
        f"image files outside the served root ({root}) are not examined",
        "picture quality, size, orientation, alt text and on-page ordering are not graded",
    ]

    return {
        "schema": "image-placement/v1",
        "checked": True,
        "nothing_to_grade": False,
        "reason": "",
        "served_root": str(root),
        "served_root_reason": root_reason,
        "data_sources": sorted({collection.source for collection in collections}),
        "collections": [
            {
                "source": collection.source,
                "path": collection.path,
                "field": collection.field,
                "items": len(collection.items),
                "distinct_images": len(
                    {_normalise_asset(i.image) for i in collection.items if i.image}
                ),
            }
            for collection in collections
        ],
        "findings": [asdict(f) for f in findings],
        "hard": has_hard_findings(findings),
        "checks": checks,
        "counts": counts,
        "not_measured": not_measured,
    }


def has_hard_findings(findings: Iterable[dict | Finding]) -> bool:
    """True when any finding is HIGH severity (a structural defect, decided by counting)."""
    for finding in findings:
        record = asdict(finding) if isinstance(finding, Finding) else finding
        if record.get("severity") in _HARD_SEVERITIES:
            return True
    return False


def format_findings(findings: Iterable[dict | Finding]) -> str:
    """Render findings as a compact, coder-facing bullet list (for FIX feedback)."""
    lines: list[str] = []
    for finding in findings:
        record = asdict(finding) if isinstance(finding, Finding) else finding
        where = f" [{record.get('file') or '?'}]"
        lines.append(f"- ({record['severity']}/{record['rule']}){where} {record['message']}")
    return "\n".join(lines)


def format_operator_summary(report: dict) -> str:
    """Render the report in the plain language the Lead Architect reads.

    Leads with what was NOT graded whenever anything was not graded. The report he was handed
    on 2026-08-08 stated a confident verdict beside an unmeasured field; putting the gap
    first is the fix for that class, not a stylistic choice.
    """
    if not report.get("checked"):
        if report.get("nothing_to_grade"):
            return (
                "The picture check found no pictures and no product list, so there was nothing "
                f"to grade. Reason: {report.get('reason', 'unknown')}"
            )
        return f"The picture check did not run. Reason: {report.get('reason', 'unknown')}"

    counts = report.get("counts", {})
    checks = report.get("checks", {})
    lines: list[str] = []

    for name, label in (("item_placement", "product pictures"), ("asset_usage", "unused pictures")):
        state = checks.get(name, {})
        if not state.get("checked", False):
            lines.append(f"NOT CHECKED - {label}: {state.get('reason', 'unknown')}")

    if checks.get("item_placement", {}).get("checked"):
        items = counts.get("items_with_image", 0)
        distinct = counts.get("distinct_item_images", 0)
        worst = counts.get("max_items_per_image", 0)
        if worst >= REPEAT_THRESHOLD:
            lines.append(
                f"{items} products share only {distinct} different pictures - one picture is used "
                f"by {worst} of them. The page repeats the same photograph."
            )
        else:
            lines.append(f"{items} products, {distinct} different pictures.")
        missing = counts.get("items_with_missing_image", 0)
        if missing:
            lines.append(f"{missing} product(s) point at a picture that is not in the delivery.")

    if checks.get("asset_usage", {}).get("checked"):
        unused = counts.get("unreferenced_assets", 0)
        if unused:
            lines.append(f"{unused} picture(s) were produced and are used nowhere.")

    # Certain findings first, inferred findings after, each labelled for what it is. ASCII
    # only throughout: this prints to a Windows console whose code page mangles non-ASCII
    # punctuation, and the operator reads the output directly.
    for finding in report.get("findings", []):
        if finding.get("severity") == SEVERITY_HIGH:
            lines.append(f"  - {finding['message']}")

    # The operator's SECOND complaint was that descriptions did not match the pictures. Those
    # findings are LOW because they are read off file names, so a HIGH-only summary would drop
    # the half he noticed first.
    suspect = [
        f for f in report.get("findings", [])
        if f.get("rule") in {"decorative-as-item", "subject-mismatch"}
    ]
    if suspect:
        lines.append(
            f"{len(suspect)} product(s) look like they are showing the wrong picture. This is "
            f"judged from file names, not by looking, so treat it as a suggestion:"
        )
        lines += [f"  - {f['message']}" for f in suspect]

    lines.append(
        "This check reads file names and product data. It never looks at the pictures "
        "themselves, so it cannot say whether a photograph is any good."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# __main__ CLI — the fleet PowerShell bridge
# ---------------------------------------------------------------------------
#
# Usage:
#   python -m shared.fleet.image_placement --site-dir <dir> [--served-root <dir>] [--operator]
#
# Stdout: a single JSON object on one line (or plain text with --operator).
#
# Exit codes:
#   0 — always for a completed grading pass, findings or not (the JSON carries the state —
#       this is a SIGNAL, matching link_lint and layout_lint; the caller decides).
#   2 — only for a usage error (no --site-dir given / directory absent).

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.image_placement",
        description="Deterministic media-placement grader for a delivered site - JSON on stdout.",
    )
    parser.add_argument("--site-dir", required=True, help="Root of the delivered site repository.")
    parser.add_argument(
        "--served-root",
        help="Directory the web server mounts at '/'. Detected when omitted.",
    )
    parser.add_argument(
        "--operator",
        action="store_true",
        help="Print the plain-language summary instead of JSON.",
    )
    args = parser.parse_args()

    if not Path(args.site_dir).is_dir():
        print(f"ERROR: --site-dir not found: {args.site_dir}", file=sys.stderr)
        sys.exit(2)

    result = grade_site(args.site_dir, args.served_root)
    print(format_operator_summary(result) if args.operator else json.dumps(result))
    sys.exit(0)
