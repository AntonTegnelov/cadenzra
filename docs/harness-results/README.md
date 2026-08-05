# Harness results

Prompt quality can only be verified against real models, so `cadenzra harness`
runs single capabilities live and reports pass rates through the *real*
validators. Results live here so prompt and surface regressions are visible
(docs/09).

Each JSON file is one measurement: capability, surface variant, model, meter,
and the pass rate within the retry budget. Failures are recorded in full, with
the validator messages that caused them.

```bash
uv run cadenzra harness voice --meter 7/8 --trials 10 --ab
```

## M2 — `generate_voice` (2026-08-05, gemini-3.6-flash)

| Variant | Meter | Bars | Trials | Converged | First attempt |
|---|---|---:|---:|---:|---:|
| cells | 5/4 (3+2) | 8 | 10 | 100% | 100% |
| cells | 7/8 (2+2+3) | 8 | 10 | 100% | 100% |
| no-cells | 7/8 (2+2+3) | 8 | 10 | 100% | 100% |
| cells | 11/8 (3+3+3+2) | 16 | 6 | 100% | 100% |

The M2 gate (≥80% converging within three attempts in 5/4 and 7/8) is met with
room to spare: every trial passed every deterministic validator on its first
attempt, including bar arithmetic, range, and the bar-check contract.

**The A/B did not discriminate, and that is the result.** Showing vetted
rhythmic cells versus withholding them produced identical pass rates, because
the task saturates — the model does not fail at it, so there is nothing for a
surface change to improve. Raising the difficulty did not help either: 11/8
grouped 3+3+3+2 across sixteen bars also converged on every first attempt. A
surface A/B only measures something once the task is hard enough to fail
sometimes, and this one is not.

**What this says about the design.** docs/04 anticipates that "free rhythmic
invention in 7/8 is where beat-count errors concentrate", and builds the
cell-anchoring surface around that expectation. Against this model, at this
scale, that expectation does not hold. Two consequences worth being explicit
about:

- The cell surface is **not currently earning its keep** as an error-prevention
  device. It is kept because it costs nothing at inference time and does real
  work for *style* — cells are how a style pack transmits its rhythmic
  character — but it should not be credited with the meter accuracy.
- The enforcement loop is still right. It is cheap, it is the only thing that
  makes correctness a guarantee rather than an observation, and a pass rate
  measured on eight-bar fragments says nothing about sixty-bar pieces, weaker
  models, or the harder layers. Measuring beats assuming in both directions.

The honest next measurement is the one that can fail: full sections under real
harmonic and material constraints, which is what M3 and M4 exercise.
