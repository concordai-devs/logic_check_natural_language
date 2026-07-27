#!/usr/bin/env python3
"""Validate the offline case library against its recorded ground truth.

For every flow: check well-formedness (single entry, no cycles, every decision
node has both branches, every path ends in an outcome — i.e. the flow denotes a
total function over atom assignments).

For every divergent case: brute-force the reference flow and the expected
extracted flow over all 2^n assignments and confirm the recorded verdict,
diverging-assignment count, and canonical counterexample.

No network, no LLM — pure recomputation. Exits non-zero on any mismatch.
"""

import itertools
import json
import sys
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(rel):
    return json.loads((EXAMPLES / rel).read_text())


def validate_constraints(constraints, atoms):
    for c in constraints:
        if c["type"] == "implies":
            assert c["if"] in atoms and c["then"] in atoms, f"constraint references unknown atom: {c}"
        elif c["type"] == "excludes":
            assert c["a"] in atoms and c["b"] in atoms, f"constraint references unknown atom: {c}"
        else:
            raise AssertionError(f"unknown constraint type {c['type']}")


def is_valid(assignment, constraints):
    """True iff the assignment satisfies all ontology constraints."""
    for c in constraints:
        if c["type"] == "implies" and assignment[c["if"]] and not assignment[c["then"]]:
            return False
        if c["type"] == "excludes" and assignment[c["a"]] and assignment[c["b"]]:
            return False
    return True


def validate_flow(nodes_list, entry, atoms):
    """Check structural well-formedness; return {node_id: node}."""
    nodes = {n["id"]: n for n in nodes_list}
    assert len(nodes) == len(nodes_list), "duplicate node ids"
    assert entry in nodes, f"entry {entry} not defined"
    for n in nodes_list:
        if n["type"] == "decision":
            assert n["atom"] in atoms, f"unknown atom {n['atom']}"
            for branch in ("true", "false"):
                assert n[branch] in nodes, f"{n['id']}.{branch} -> missing node"
        else:
            assert n["type"] == "outcome", f"unknown node type {n['type']}"
    # acyclicity via DFS from entry
    state = {}  # id -> 1 (visiting) | 2 (done)

    def dfs(nid):
        if state.get(nid) == 1:
            raise AssertionError(f"cycle through {nid}")
        if state.get(nid) == 2:
            return
        state[nid] = 1
        node = nodes[nid]
        if node["type"] == "decision":
            dfs(node["true"])
            dfs(node["false"])
        state[nid] = 2

    dfs(entry)
    return nodes


def evaluate(nodes, entry, assignment):
    nid = entry
    while nodes[nid]["type"] == "decision":
        node = nodes[nid]
        nid = node["true"] if assignment[node["atom"]] else node["false"]
    return nodes[nid]["outcome"]


def compare(ref_nodes, ref_entry, doc_nodes, doc_entry, atom_ids, constraints):
    """Compare flows over all constraint-satisfying (valid) assignments.

    Returns (diverging, valid_count) where diverging is a list of
    (assignment, ref_outcome, doc_outcome) for valid assignments that disagree.
    """
    diverging = []
    valid_count = 0
    for values in itertools.product([False, True], repeat=len(atom_ids)):
        assignment = dict(zip(atom_ids, values))
        if not is_valid(assignment, constraints):
            continue
        valid_count += 1
        r = evaluate(ref_nodes, ref_entry, assignment)
        d = evaluate(doc_nodes, doc_entry, assignment)
        if r != d:
            diverging.append((assignment, r, d))
    return diverging, valid_count


def main():
    index = load("index.json")
    failures = 0
    flows = {}  # path -> (nodes, entry, atom_ids, constraints)

    for case in index["cases"]:
        cid = case["id"]
        try:
            flow_path = case["flow"]
            if flow_path not in flows:
                flow = load(flow_path)
                atom_ids = [a["id"] for a in flow["ontology"]["atoms"]]
                constraints = flow["ontology"].get("constraints", [])
                validate_constraints(constraints, set(atom_ids))
                nodes = validate_flow(flow["nodes"], flow["entry"], set(atom_ids))
                flows[flow_path] = (nodes, flow["entry"], atom_ids, constraints)
            ref_nodes, ref_entry, atom_ids, constraints = flows[flow_path]

            assert (EXAMPLES / case["document"]).exists(), "document file missing"

            if case["expected_verdict"] == "EQUIVALENT":
                assert case["ground_truth"] is None
                print(f"  ok  {cid}: flow well-formed, document present (faithful)")
                continue

            gt = load(case["ground_truth"])
            doc_flow = gt["expected_extracted_flow"]
            doc_nodes = validate_flow(doc_flow["nodes"], doc_flow["entry"], set(atom_ids))

            diverging, valid_count = compare(
                ref_nodes, ref_entry, doc_nodes, doc_flow["entry"], atom_ids, constraints
            )
            total = 2 ** len(atom_ids)

            assert gt["expected_verdict"] == "DIVERGENT" and diverging, (
                f"expected DIVERGENT but flows are equivalent on all valid assignments"
            )
            assert gt["total_assignments"] == total, (
                f"total_assignments {gt['total_assignments']} != {total}"
            )
            assert gt.get("valid_assignments", total) == valid_count, (
                f"recorded {gt.get('valid_assignments')} valid assignments, recomputed {valid_count}"
            )
            assert gt["diverging_assignment_count"] == len(diverging), (
                f"recorded {gt['diverging_assignment_count']} diverging assignments, "
                f"recomputed {len(diverging)}"
            )

            cx = gt["canonical_counterexample"]
            assert is_valid(cx["assignment"], constraints), (
                "canonical counterexample violates ontology constraints"
            )
            r = evaluate(ref_nodes, ref_entry, cx["assignment"])
            d = evaluate(doc_nodes, doc_flow["entry"], cx["assignment"])
            assert r == cx["reference_outcome"], (
                f"counterexample reference outcome: recorded {cx['reference_outcome']}, actual {r}"
            )
            assert d == cx["document_outcome"], (
                f"counterexample document outcome: recorded {cx['document_outcome']}, actual {d}"
            )
            assert r != d, "canonical counterexample does not diverge"

            print(
                f"  ok  {cid}: {len(diverging)}/{valid_count} valid assignments diverge "
                f"({total} raw), counterexample verified"
            )
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {cid}: {e}")

    print(f"\n{len(index['cases'])} cases checked, {failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
