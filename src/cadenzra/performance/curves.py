"""Dynamics plans to continuous controller curves.

A printed hairpin tells a performer to grow; it does nothing to a synthesizer.
Realizing the plan as CC11 is what makes a held-chord crescendo *sound* rather
than merely print — which is the reason the score/performance split exists at
all (docs/02).

Both projections come from the same `DynamicsPlan`, so the printed dynamics and
the audible shape cannot drift apart on the plan's own terms. Sub-arc shaping a
generator adds in the notation affects velocities only; the critic is the loose
check that print and sound agree (docs/03).
"""

from fractions import Fraction
from typing import Final

from pydantic import BaseModel

from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.time import offset_of, section_length
from cadenzra.model.structure import DynamicsPlan

EXPRESSION_CONTROLLER: Final = 11

# The Italian dynamics, as controller values. The spacing is perceptual rather
# than linear: the ear hears pp-to-p as a bigger step than f-to-ff.
DYNAMIC_LEVELS: Final[dict[str, int]] = {
    "ppp": 16,
    "pp": 28,
    "p": 45,
    "mp": 62,
    "mf": 78,
    "f": 96,
    "ff": 112,
    "fff": 127,
}
DEFAULT_LEVEL: Final = DYNAMIC_LEVELS["mf"]

# How finely a ramp is sampled. One step per sixteenth is inaudibly smooth and
# keeps the event count sane over a long piece.
CURVE_RESOLUTION: Final = Fraction(1, 16)


class CurvePoint(BaseModel, frozen=True):
    """One controller event: where it lands, and what it sets."""

    offset: Fraction
    value: int


def level_of(name: str) -> int:
    """The controller value for a dynamic marking."""
    return DYNAMIC_LEVELS.get(name.strip().lower(), DEFAULT_LEVEL)


def dynamics_plan_to_cc_events(
    plan: DynamicsPlan,
    bars: int,
    meter: MeterSpec,
    *,
    intensity: float = 1.0,
    resolution: Fraction = CURVE_RESOLUTION,
) -> list[CurvePoint]:
    """A section's dynamics arc as a ramped CC11 curve.

    `intensity` scales the *distance from the middle*, so turning it down
    flattens the arc toward mf rather than making everything quieter — the
    critic's "the dynamics are too extreme" becomes a knob, not a rewrite
    (docs/02).
    """
    total = section_length(bars, meter)
    waypoints = _waypoints(plan, bars, meter, total)

    points = [CurvePoint(offset=Fraction(0), value=_scaled(waypoints[0][1], intensity))]
    for (start, from_level), (end, to_level) in zip(
        waypoints, waypoints[1:], strict=False
    ):
        points += _ramp(start, end, from_level, to_level, intensity, resolution)
    return _without_repeats(points)


def _waypoints(
    plan: DynamicsPlan, bars: int, meter: MeterSpec, total: Fraction
) -> list[tuple[Fraction, int]]:
    """The arc as (offset, level) pairs, starting at zero and ending at the end."""
    points = [(Fraction(0), level_of(plan.start))]
    for target in plan.targets:
        bar = min(max(target.bar, 1), bars)
        points.append((offset_of(bar, 1, meter), level_of(target.level)))
    if points[-1][0] < total:
        # Hold the final level to the end of the section rather than letting
        # the curve stop early and leave the tail at whatever it last was.
        points.append((total, points[-1][1]))
    return points


def _ramp(
    start: Fraction,
    end: Fraction,
    from_level: int,
    to_level: int,
    intensity: float,
    resolution: Fraction,
) -> list[CurvePoint]:
    """Intermediate points between two waypoints, inclusive of the endpoint."""
    from_value = _scaled(from_level, intensity)
    to_value = _scaled(to_level, intensity)
    if end <= start:
        return [CurvePoint(offset=end, value=to_value)]
    if from_value == to_value:
        return [CurvePoint(offset=end, value=to_value)]

    span = end - start
    steps = max(1, int(span / resolution))
    points = []
    for step in range(1, steps + 1):
        position = Fraction(step, steps)
        points.append(
            CurvePoint(
                offset=start + span * position,
                value=_clamp(
                    round(from_value + (to_value - from_value) * float(position))
                ),
            )
        )
    return points


def _scaled(level: int, intensity: float) -> int:
    """Scale a level's distance from the middle, not its absolute value."""
    return _clamp(round(DEFAULT_LEVEL + (level - DEFAULT_LEVEL) * intensity))


def _clamp(value: int) -> int:
    return max(0, min(127, value))


def _without_repeats(points: list[CurvePoint]) -> list[CurvePoint]:
    """Drop consecutive duplicates — a controller that does not change is noise."""
    kept: list[CurvePoint] = []
    for point in points:
        if kept and kept[-1].value == point.value:
            continue
        kept.append(point)
    return kept
