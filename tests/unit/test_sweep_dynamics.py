"""The sweep controller, pinned by simulation instead of billed runs.

The cross-voice repair loop is a stochastic controller: each sweep repairs
routed faults (fixing each with some probability) and every edit risks
injecting a fresh fault. Its stopping rule and budget were tuned live, one
billed run per lesson — 65→53→60 and 47→24→14→7→13→7 both killed while
descending. These tests replay that tuning against a seeded fault-dynamics
model, so any change to `sweep_plateaued` or the section budget must
re-prove convergence here, for free.

The regimes are taken from the measured runs: repairs cleared roughly 60%
of routed faults per sweep while injecting fresh ones at roughly a third
of that rate; a broken controller (injection matching the fix rate) must
go loud instead of looping.
"""

import random

from cadenzra.app.compose import sweep_plateaued
from cadenzra.app.config import RetryBudgets

BUDGET = RetryBudgets().section


def _run(
    rng: random.Random, *, start: int, fix: float, inject: float
) -> tuple[str, list[int]]:
    """One simulated sweep loop: ('converged'|'plateaued'|'exhausted', path)."""
    faults = start
    trajectory: list[int] = []
    for _ in range(BUDGET):
        if faults == 0:
            return "converged", trajectory
        trajectory.append(faults)
        if sweep_plateaued(trajectory):
            return "plateaued", trajectory
        fixed = sum(1 for _ in range(faults) if rng.random() < fix)
        injected = sum(1 for _ in range(faults) if rng.random() < inject)
        faults = faults - fixed + injected
    if faults == 0:
        return "converged", trajectory
    return "exhausted", trajectory


def test_the_measured_live_regime_converges_within_the_budget() -> None:
    """The healthy regime (fix ≈ 0.6, inject ≈ 0.2, first sweeps ≈ 40-70
    faults) must almost always converge before the plateau guard or the
    budget fires — this is the regime the guard was killing at patience 2."""
    rng = random.Random(20260811)
    outcomes = [
        _run(rng, start=rng.randint(40, 70), fix=0.6, inject=0.2)[0]
        for _ in range(100)
    ]

    converged = outcomes.count("converged")
    assert converged >= 90, f"only {converged}/100 converged: {outcomes}"


def test_a_non_converging_regime_goes_loud_not_long() -> None:
    """When injection matches the fix rate the loop cannot converge; the
    plateau guard must end it well before the budget would."""
    rng = random.Random(20260811)
    results = [
        _run(rng, start=rng.randint(40, 70), fix=0.3, inject=0.3)
        for _ in range(100)
    ]

    assert all(outcome != "converged" for outcome, _ in results)
    plateaued = sum(1 for outcome, _ in results if outcome == "plateaued")
    assert plateaued >= 90, "the guard, not the budget, ends a stuck loop"


def test_the_guard_tolerates_the_measured_noise_at_the_tail() -> None:
    """The exact trajectories the two-sweep guard killed while they were
    still descending must survive the current rule at every prefix."""
    for killed_live in ([47, 24, 14, 7, 13, 7], [60, 31, 25, 20, 12, 17, 12]):
        for length in range(1, len(killed_live) + 1):
            assert not sweep_plateaued(killed_live[:length]), killed_live[:length]


def test_a_proven_plateau_still_fires() -> None:
    assert sweep_plateaued([263, 63, 66, 64, 65])


def test_the_tail_is_bounded_by_the_budget_not_the_guard() -> None:
    """At the last few faults a sweep costs a handful of patches and noise
    dominates any trend; the guard killing 13% of converging loops there
    was measured by the simulation above. The budget is the honest bound."""
    assert not sweep_plateaued([1, 1, 1, 1])
    assert not sweep_plateaued([47, 24, 3, 3, 3, 3])
