#!/usr/bin/env python3
"""Build the self-contained interactive demo page.

Inlines the whole case library — documents, reference and extracted flows,
ontologies, ground truth, Lean theorems — into tools/demo_template.html and
writes the finished page to the path given as argv[1].

Before writing, the embedded data is re-verified with the same brute-force
comparison used by the other tools, so the page can never ship data that
disagrees with the repo.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_examples import EXAMPLES, load, validate_flow, compare  # noqa: E402

REPO = EXAMPLES.parent

TITLES = {
    "severance-faithful": ("Severance clause — draft A", "Employment"),
    "severance-statutory-floor-dropped": ("Severance clause — draft B", "Employment"),
    "severance-notice-branch-flipped": ("Severance clause — draft C", "Employment"),
    "severance-constructive-dismissal-dropped": ("Severance clause — draft D", "Employment"),
    "claim-faithful": ("Claim payout clause — draft A", "Insurance"),
    "claim-late-notice-escalated": ("Claim payout clause — draft B", "Insurance"),
}

SHORT_LABELS = {
    "terminated_for_cause": "Cause?",
    "gross_misconduct": "Gross misconduct?",
    "voluntary_resignation": "Resigned?",
    "constructive_dismissal": "Constructive dismissal?",
    "served_12_months": "12 months served?",
    "served_5_years": "5 years served?",
    "redundancy": "Redundancy?",
    "suitable_alternative_offered": "Alt. role offered?",
    "written_notice_given": "Written notice?",
    "policy_in_force": "Policy in force?",
    "excluded_peril": "Excluded peril?",
    "loss_exceeds_deductible": "Above deductible?",
    "notice_within_30_days": "Notice ≤ 30 days?",
    "documentation_complete": "Docs complete?",
}

OUTCOMES = {
    "NO_SEVERANCE": {"label": "No severance", "tone": "bad"},
    "STATUTORY_MINIMUM": {"label": "Statutory minimum", "tone": "mid"},
    "STANDARD_SEVERANCE": {"label": "Standard severance", "tone": "good"},
    "ENHANCED_SEVERANCE": {"label": "Enhanced severance", "tone": "good"},
    "PREMIUM_REDUNDANCY": {"label": "Premium redundancy", "tone": "good"},
    "DENIED": {"label": "Denied", "tone": "bad"},
    "BELOW_DEDUCTIBLE": {"label": "Below deductible", "tone": "mid"},
    "FULL_PAYMENT": {"label": "Full payment", "tone": "good"},
    "REDUCED_PAYMENT": {"label": "Reduced payment", "tone": "mid"},
}


def camel(cid):
    return "".join(w.capitalize() for w in re.split(r"[-_]", cid))


def doc_text(rel):
    text = (EXAMPLES / rel).read_text()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = [ln for ln in text.splitlines() if not ln.startswith("# ")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def lean_theorems(cid):
    src = (REPO / "lean" / "cases" / f"{camel(cid)}.lean").read_text()
    lines = src.splitlines()
    last_eval = max(i for i, ln in enumerate(lines) if ln.startswith("#eval"))
    return "\n".join(lines[last_eval + 1:]).strip()


def main():
    out_path = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
    index = load("index.json")
    verdicts = {v["case"]: v for v in load("verdicts.json")["verdicts"]}
    cases = []

    for case in index["cases"]:
        cid = case["id"]
        flow = load(case["flow"])
        ext = load(case["extracted"])["flow"]
        atoms = flow["ontology"]["atoms"]
        atom_ids = [a["id"] for a in atoms]
        constraints = flow["ontology"].get("constraints", [])

        # re-verify what we are about to embed
        ref_nodes = validate_flow(flow["nodes"], flow["entry"], set(atom_ids))
        ext_nodes = validate_flow(ext["nodes"], ext["entry"], set(atom_ids))
        diverging, valid = compare(ref_nodes, flow["entry"], ext_nodes, ext["entry"], atom_ids, constraints)
        o = verdicts[cid]
        assert len(diverging) == o["diverging_assignment_count"] and valid == o["valid_assignments"], cid

        gt = None
        if case["ground_truth"]:
            g = load(case["ground_truth"])
            quotes = g["planted_flaw"].get("quotes", [])
            # every quote must occur verbatim (modulo whitespace) in the page text,
            # or the highlight would silently fail to render
            page_text = doc_text(case["document"])
            for q in quotes:
                rx = r"\s+".join(re.escape(w) for w in q.split())
                assert re.search(rx, page_text), f"{cid}: flaw quote not found in document: {q[:60]}…"
            gt = {
                "clause": g["planted_flaw"]["clause"],
                "kind": g["planted_flaw"]["kind"],
                "summary": g["planted_flaw"]["summary"],
                "quotes": quotes,
                "narrative": g["canonical_counterexample"]["narrative"],
                "reference_outcome": g["canonical_counterexample"]["reference_outcome"],
                "document_outcome": g["canonical_counterexample"]["document_outcome"],
                "assignment": g["canonical_counterexample"]["assignment"],
            }

        title, domain = TITLES[cid]
        cases.append({
            "id": cid,
            "title": title,
            "domainLabel": domain,
            "document": "examples/" + case["document"],
            "flowId": flow["id"],
            "text": doc_text(case["document"]),
            "ontology": {
                "atoms": [{"id": a["id"], "question": a["question"]} for a in atoms],
                "constraints": constraints,
            },
            "refFlow": {"entry": flow["entry"], "nodes": flow["nodes"]},
            "extFlow": {"entry": ext["entry"], "nodes": ext["nodes"]},
            "groundTruth": gt,
            "lean": lean_theorems(cid),
            "leanPath": f"lean/cases/{camel(cid)}.lean",
            "leanFull": (REPO / "lean" / "cases" / f"{camel(cid)}.lean").read_text().strip(),
        })

    data = {"shortLabels": SHORT_LABELS, "outcomes": OUTCOMES, "cases": cases}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    template = (REPO / "tools" / "demo_template.html").read_text()
    assert "/*__DATA__*/" in template
    page = template.replace("/*__DATA__*/", blob)

    # --bare: emit page content only (for hosts that add the document shell,
    # e.g. claude.ai artifacts). Default: full standalone HTML document.
    if "--bare" not in sys.argv:
        page = (
            "<!doctype html>\n"
            "<!-- GENERATED FILE - do not edit. "
            "Edit tools/demo_template.html (or examples/) and run: "
            "python3 tools/build_demo.py demo/index.html -->\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "</head>\n<body>\n" + page + "\n</body>\n</html>\n"
        )
    out_path.write_text(page)
    print(f"wrote {out_path} ({out_path.stat().st_size // 1024} KB, {len(cases)} cases, data re-verified)")


if __name__ == "__main__":
    main()
