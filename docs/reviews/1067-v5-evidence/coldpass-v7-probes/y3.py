"""Y3: TRUE maximal vocabulary (every token in BOTH partitions, _partition
bypassed) vs the grader's two-pass screen, over the shipped 26."""
import sys, json, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg
from shared.grading import coordinator_graduation as cg

G = pg.ProseGuard()

def excused_maximal(body, tokens, run_id):
    """_claim_is_excused with the maximal vocabulary — the real upper bound."""
    if pg._UNCERTAIN_PUNCT.search(body):
        return False
    terms = pg._usable_terms(frozenset(tokens))
    form = pg._build_sentence_form(terms, terms, run_id)
    sents = [s.strip() for s in pg._SENTENCE_SPLIT.split(body.strip()) if s.strip()]
    if not sents:
        return False
    return all(form.fullmatch(s) is not None and pg._asserts_no_majority(s)
               for s in sents)

def strip_prefix(t):
    for tok in ("INCOMPLETE:", "PARKED:", "SUCCEEDED:"):
        if t.startswith(tok):
            return t[len(tok):]
    return t

def two_pass_caught(text, truth):
    toks = sorted(set(cg._IDENTIFIERISH.findall(text)))
    for result in (pg.RESULT_MERGED, pg.RESULT_PARKED):
        v = tuple((t, result) for t in toks)
        if G.validate_run_summary(truth, text, task_results=v).accepted:
            return False
    return True

rows = [json.loads(l) for l in pathlib.Path(
    r"C:/Users/mrbla/wt-1067-v7/shared/grading/data/coordinator_guard_adversarial_corpus.jsonl"
).read_text(encoding="utf-8").splitlines() if l.strip()]

over = []
for r in rows:
    t = pg.RunTruth(r.get("case_id","c"), bool(r.get("oracle_passed")),
                    bool(r.get("merged")), bool(r.get("parked")))
    text = r["text"]
    toks = set(cg._IDENTIFIERISH.findall(text))
    caught = two_pass_caught(text, t)
    maximal_excuse = excused_maximal(strip_prefix(text), toks, t.run_id)
    if caught and maximal_excuse:
        over.append(r.get("case_id"))
print(f"corpus cases: {len(rows)}")
print(f"counted CAUGHT by the two-pass screen but EXCUSABLE under a maximal")
print(f"vocabulary (i.e. over-counted today): {len(over)}  {over}")
print()
print("Constructed demonstration that the class is real:")
T = pg.RunTruth("case-mixed", False, True, False)
S = ("INCOMPLETE: The run did not complete successfully, but bill-splitter was "
     "merged and acceptance-tests was parked.")
print("  ", S)
print("   production (mixed vocab)  ->", G.validate_run_summary(
        T, S, task_results=(("bill-splitter","MERGED"),("acceptance-tests","PARKED"))).accepted)
print("   two-pass screen caught?   ->", two_pass_caught(S, T))
