# Verdict archive — BOUNTY-002 (closed 2026-10-12)

**Reproduce everything yourself.** No trust required.

| File | What it is |
|---|---|
| `bounty2_verdict_2lll5.json` | Final verdict for PR #9 (2lll5): lift 1.4002, label-permutation p=0.0001, frequency control 1.0204 → GATE-3 PASSED |
| `bounty2_judge_2lll5_run.py` | The judge, verbatim: data-consistency assertion (public prefix == full N=3511), anchor reproduction (yuruyang 4851/3111, lift 1.429363548698168), verbatim-vs-vectorized cross-check (0/699 mismatch), 10,000 label permutations, cumulative-frequency control |

**Verdict correction (2026-10-12).** GATE-1 (mechanism recovery — transfer matrix / generation function / hidden driver) was required by the task text but never implemented as an auditable check. All seven "QUALIFIED" labels were GATE-3-only and are corrected to **GATE-3 PASSED** (archive credit + free access, see `../HALL_OF_CONTRIBUTORS.md`). No GATE-1 pass = no cash trigger. BOUNTY-002 is closed.

**Reference ceiling:** a predictor with perfect per-tick regime knowledge reaches 3.52/6 mean hits (lift ≈ 3.23) — the generator is 3-regime switching with a recoverable driver. The distance from lift 1.4 to 3.23 is exactly the last mile this bounty asked for. Nobody cleared it. The referee could not audit it. That was our error, and it is why this bounty is closed.
