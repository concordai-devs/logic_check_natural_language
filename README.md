# logic_check_natural_language

**Formal verification of legal clauses against agreed decision logic — an MVP.**

Given a decision policy the parties have agreed on (e.g. a severance policy from a
term sheet) and a drafted contract clause that is supposed to implement it, this
project proves — in Lean 4 — whether the clause's logic is equivalent to the
policy, or produces a concrete counterexample: a legally possible scenario in
which the contract and the policy give different outcomes.

The framing in one line: **LLMs read, Lean reasons, humans audit counterexamples
instead of re-reading documents.**

## How it works

The pipeline has four stages, all of which run **offline** — every artifact is
curated, version-controlled, and machine-checkable. There are no live API calls.

```
1. Reference flow        flow.json          hand-authored decision logic per legal domain
2. Clause generation     clause_*.md        LLM-authored contract prose (offline, curated)
3. Logic extraction      extracted/*.json   prose mapped back onto the same ontology (offline)
4. Lean verification     lean/cases/*.lean  kernel-checked equivalence / divergence proofs
```

### 1. Reference logic flows

Each legal domain gets a **fixed ontology** — boolean atoms ("terminated for
cause?", "5 years served?"), **constraints** ruling out legally impossible
combinations (5 years of service implies 12 months; cause, resignation, and
redundancy are mutually exclusive), and named outcomes — plus a **decision flow**
over it: a rooted, acyclic binary decision diagram in which every scenario
reaches exactly one outcome. A flow denotes a total function from atom
assignments to outcomes; equivalence of two flows is quantified over the
constraint-satisfying ("valid") assignments only.

Two domains are included: employment severance
([`examples/termination_severance/flow.json`](examples/termination_severance/flow.json)
— 9 atoms, 7 constraints, 5 outcomes, 42 valid worlds of 512) and insurance claim
payout ([`examples/claim_eligibility/flow.json`](examples/claim_eligibility/flow.json)
— deliberately simple: 5 atoms, 32 worlds).

### 2. Synthetic clause generation (offline)

Contract prose is LLM-authored from a flow. **Faithful** cases render the
reference logic exactly. **Divergent** cases first apply a structural mutation to
the flow — promote a qualifier to a gate, flip a branch, drop a carve-out,
escalate a penalty — and then render the *mutated* logic faithfully. Because the
divergence is injected in the tree rather than by asking a model to "make a
mistake", ground truth is exact by construction; it is recorded per case in a
`divergence.json` (the flaw, the flow the document actually implements, the
diverging-scenario count, and a canonical counterexample with a plain-language
narrative). Divergent documents are reworded and renumbered against their
faithful siblings, so string diffing finds nothing.

The library has 6 cases (2 faithful, 4 divergent), indexed in
[`examples/index.json`](examples/index.json).

### 3. Extraction (offline)

Each document is read back and mapped onto the same ontology, producing an
**extracted flow** ([`examples/extracted/`](examples/extracted/)) — the
document's logic as the reader understood it. Extraction accuracy is measured
against the recorded ground truth, not assumed (currently 6/6 semantically
exact).

### 4. Lean verification

[`tools/lean_verify.py`](tools/lean_verify.py) compiles each case — both flows,
the outcome type, and the validity predicate — into a self-contained Lean 4 file
(core only, no mathlib; ~0.7 s per case). Lean enumerates the counterexamples in
a probe pass, then the classification theorems are appended and checked by the
kernel via `decide`:

```lean
-- divergent case
theorem divergent : counterexamples ≠ [] := by decide
theorem divergent_count : counterexamples.length = 8 := by decide

-- faithful case
theorem equivalent : counterexamples = [] := by decide
```

The proof artifacts live in [`lean/cases/`](lean/cases/). A Python
implementation of the same semantics
([`tools/verify_extractions.py`](tools/verify_extractions.py)) is kept as an
independent oracle: the two share no code, and `lean_verify.py` fails if they
ever disagree.

## Running the checks

Requires Python 3 (stdlib only) and, for the proofs, Lean 4 via
[elan](https://github.com/leanprover/elan).

```sh
python3 tools/check_examples.py       # validate the library against its recorded ground truth
python3 tools/verify_extractions.py   # verdicts for extracted vs reference flows; writes examples/verdicts.json
python3 tools/lean_verify.py          # generate + kernel-check the Lean proofs; cross-checks the oracle
python3 tools/build_demo.py out.html  # build the self-contained interactive demo page
```

Expected output: all 6 cases pass, with verdicts
`EQUIVALENT` (×2) and `DIVERGENT` with 8/42, 4/42, 6/42, and 2/32 diverging
valid scenarios.

## Launching the web app

The interactive demo is a single self-contained HTML file — no server, no
network, no dependencies. All case data (documents, flows, ground truth, Lean
theorems) is inlined at build time and re-verified against the repo, and the
exhaustive equivalence check runs live in the browser. A pre-built copy is
committed at [`demo/index.html`](demo/index.html); just open it:

```sh
open demo/index.html            # macOS (Linux: xdg-open, Windows: start)
```

Or serve it, if you prefer a URL:

```sh
python3 -m http.server 8000 --directory demo
# then visit http://localhost:8000
```

After changing anything in `examples/` or `lean/cases/`, rebuild the page:

```sh
python3 tools/build_demo.py demo/index.html
```

The build fails rather than ship stale data: it re-runs the brute-force
verification on everything it embeds and aborts on any mismatch with
`examples/verdicts.json`.

In the app: pick one of the six clause drafts (labelled neutrally so the
verdict isn't spoiled), inspect the contract text and the two flow diagrams
(reference vs. extracted), and press **Run certification**. Divergent cases
reveal the flawed clause highlighted in the text, the counterexample scenarios,
and the kernel-checked Lean theorems; the scenario explorer lets you toggle the
facts of a case and trace both logic paths live.

## The case library

| Case | Domain | Verdict | Planted flaw |
|---|---|---|---|
| `severance-faithful` | Employment | EQUIVALENT | — |
| `severance-statutory-floor-dropped` | Employment | DIVERGENT (8/42) | 12-month qualifier drafted as a gate on all severance, deleting the statutory floor |
| `severance-notice-branch-flipped` | Employment | DIVERGENT (4/42) | notice condition drafted the wrong way round in the tenure test |
| `severance-constructive-dismissal-dropped` | Employment | DIVERGENT (6/42) | constructive-dismissal carve-out silently missing |
| `claim-faithful` | Insurance | EQUIVALENT | — |
| `claim-late-notice-escalated` | Insurance | DIVERGENT (2/32) | late notice drafted as full denial instead of a 15% reduction |

## Repository layout

```
examples/
  index.json                        case manifest
  termination_severance/            flow.json + clause documents + divergence ground truth
  claim_eligibility/                flow.json + clause documents + divergence ground truth
  extracted/<case-id>.json          stage-3 output: extracted flow per document
  verdicts.json                     per-case verdict + counterexample (demo input)
demo/
  index.html                        pre-built interactive demo (self-contained, open in a browser)
lean/
  cases/<CaseId>.lean               stage-4 proof artifacts (Lean 4, core only)
tools/
  check_examples.py                 ground-truth checker (brute force over valid worlds)
  verify_extractions.py             Python verification oracle; writes verdicts.json
  lean_verify.py                    Lean codegen + proof check + oracle cross-check
  build_demo.py, demo_template.html interactive demo page builder (inlines + re-verifies all data)
```

## Scope of the guarantee

The formal layer proves that two logic flows — the agreed reference and the flow
extracted from the prose — agree or disagree on every legally possible scenario.
It does **not** prove that extraction read the document correctly; that step is
measured against ground truth and remains human-auditable. Open-textured legal
terms ("material breach", "suitable alternative") live inside the atoms, where
interpretation remains a human judgment. The model targets decision-procedural
clauses (eligibility, remedies, thresholds), not deontic or temporal structure.
