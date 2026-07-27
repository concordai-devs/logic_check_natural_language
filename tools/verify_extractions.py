#!/usr/bin/env python3
"""Verify chat-extracted flows against the reference flows (offline stage-4 mock).

This performs, in Python, exactly what the Lean stage will prove:
for each case, compare the REFERENCE flow against the EXTRACTED flow
(the stage-3 output saved under examples/extracted/) over all
constraint-satisfying assignments, and produce a verdict —
EQUIVALENT, or DIVERGENT with counterexamples.

It additionally scores the extraction itself: the extracted flow must be
semantically identical (over valid worlds) to the case's ground-truth
expected_extracted_flow (for faithful cases, the reference flow itself).
This measures "did the extractor read the document correctly", separately
from "does the document match the reference".

Results are written to examples/verdicts.json for the front-end.
No network, no LLM. Exits non-zero on any mismatch.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_examples import (  # noqa: E402
    EXAMPLES, load, validate_flow, validate_constraints, is_valid, evaluate, compare,
)


def nodes_of(flow, atoms):
    return validate_flow(flow["nodes"], flow["entry"], atoms), flow["entry"]


def main():
    index = load("index.json")
    failures = 0
    verdicts = []

    for case in index["cases"]:
        cid = case["id"]
        try:
            ref_flow = load(case["flow"])
            atom_ids = [a["id"] for a in ref_flow["ontology"]["atoms"]]
            atoms = set(atom_ids)
            constraints = ref_flow["ontology"].get("constraints", [])
            validate_constraints(constraints, atoms)
            ref_nodes, ref_entry = nodes_of(ref_flow, atoms)

            extraction = load(case["extracted"])
            ext_nodes, ext_entry = nodes_of(extraction["flow"], atoms)

            # 1. The verification proper: reference vs extracted
            diverging, valid_count = compare(
                ref_nodes, ref_entry, ext_nodes, ext_entry, atom_ids, constraints
            )
            verdict = "DIVERGENT" if diverging else "EQUIVALENT"
            assert verdict == case["expected_verdict"], (
                f"verdict {verdict}, expected {case['expected_verdict']}"
            )

            # 2. Extraction scoring: extracted vs ground-truth document flow
            if case["ground_truth"]:
                gt = load(case["ground_truth"])
                target = gt["expected_extracted_flow"]
                target_nodes, target_entry = nodes_of(target, atoms)
            else:
                target_nodes, target_entry = ref_nodes, ref_entry
            ext_errors, _ = compare(
                ext_nodes, ext_entry, target_nodes, target_entry, atom_ids, constraints
            )
            assert not ext_errors, (
                f"extraction disagrees with ground-truth document semantics on "
                f"{len(ext_errors)} valid assignment(s), e.g. {ext_errors[0]}"
            )

            entry = {
                "case": cid,
                "verdict": verdict,
                "valid_assignments": valid_count,
                "diverging_assignment_count": len(diverging),
                "extraction_matches_ground_truth": True,
            }
            if diverging:
                gt = load(case["ground_truth"])
                entry["canonical_counterexample"] = gt["canonical_counterexample"]
            verdicts.append(entry)
            print(
                f"  ok  {cid}: {verdict}"
                + (f" ({len(diverging)}/{valid_count} valid assignments)" if diverging else "")
                + " — extraction matches ground truth"
            )
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {cid}: {e}")

    out = EXAMPLES / "verdicts.json"
    out.write_text(json.dumps({"verdicts": verdicts}, indent=2) + "\n")
    print(f"\n{len(index['cases'])} cases verified, {failures} failure(s); wrote {out.relative_to(EXAMPLES.parent)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
