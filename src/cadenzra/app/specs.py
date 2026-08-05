"""The specs the project is verified against, as data.

Style enters the system as data and never as code, so these are just values —
a Tool-inspired choir piece, a fugue, and something deliberately unlike either.
Three genuinely different styles going through unchanged pipeline code is what
"genre-general" means operationally (docs/01, success criterion 4).
"""

from cadenzra.model.primitives.meter import MeterSpec, simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec

FIVE_FOUR: MeterSpec = simple_meter(5, 4, [3, 2])
SEVEN_EIGHT: MeterSpec = simple_meter(7, 8, [2, 2, 3])
FOUR_FOUR: MeterSpec = simple_meter(4, 4)
SIX_EIGHT: MeterSpec = simple_meter(6, 8, [3, 3])


def _voice(
    voice_id: str,
    low: str,
    high: str,
    *,
    program: int = 52,
    lyrics: bool = True,
    group: str | None = None,
) -> VoiceSpec:
    return VoiceSpec(
        voice_id=voice_id,
        kind="vocal" if lyrics else "instrument",
        group=group,
        range_low=Pitch.from_scientific(low),
        range_high=Pitch.from_scientific(high),
        midi_program=program,
        lyrics=lyrics,
    )


SATB = [
    _voice("soprano", "C4", "A5", group="upper"),
    _voice("alto", "G3", "D5", group="upper"),
    _voice("tenor", "C3", "G4", group="lower"),
    _voice("bass", "E2", "C4", group="lower"),
]


TOOL_CHOIR = PieceSpec(
    title="Vessel",
    style_prompt=(
        "Tool-inspired writing for unaccompanied SATB choir: dark and modal, "
        "Lydian and Phrygian colorings over a low drone, shifting odd meters that "
        "feel deliberate rather than clever. Alternate between heavy passages "
        "where the whole choir moves in rhythmic unison and quiet polyphonic ones "
        "where the lines drift apart. Long held chords that swell. A long dynamic "
        "arc across the whole piece, from near silence to overwhelming."
    ),
    voices=SATB,
    meters_allowed=[SEVEN_EIGHT, FIVE_FOUR, FOUR_FOUR],
    key_center="d",
    target_minutes=3.0,
    tempo_bpm=88,
    language="English",
)


FUGUE = PieceSpec(
    title="Fugue in D minor",
    style_prompt=(
        "A strict four-voice fugue for string quartet in the Baroque manner. A "
        "clearly shaped subject, a real exposition with each voice entering in "
        "turn — subject, tonal answer at the fifth, subject, answer — a "
        "countersubject that works in invertible counterpoint, episodes built from "
        "fragments of the subject, and a final entry over a dominant pedal."
    ),
    voices=[
        _voice("violin1", "G3", "E6", program=40, lyrics=False, group="upper"),
        _voice("violin2", "G3", "C6", program=40, lyrics=False, group="upper"),
        _voice("viola", "C3", "E5", program=41, lyrics=False, group="lower"),
        _voice("cello", "C2", "G4", program=42, lyrics=False, group="lower"),
    ],
    meters_allowed=[FOUR_FOUR],
    key_center="d minor",
    target_minutes=2.5,
    tempo_bpm=96,
)


# The genre-generality check: nothing about this resembles the other two, and
# it must pass through the same pipeline code untouched.
SYNTHWAVE = PieceSpec(
    title="Night Drive",
    style_prompt=(
        "Synthwave instrumental: a bright arpeggiated synth line over a driving "
        "bass, warm major-seventh and sus chords, long-held pad notes underneath, "
        "an unhurried four-on-the-floor feel. Nostalgic and propulsive, nothing "
        "dissonant, parallel fifths entirely welcome."
    ),
    voices=[
        _voice("lead", "C4", "C6", program=81, lyrics=False),
        _voice("pad", "C3", "C5", program=89, lyrics=False),
        _voice("bass", "E1", "E3", program=39, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR, SIX_EIGHT],
    key_center="a minor",
    target_minutes=2.0,
    tempo_bpm=104,
)


# Two sections, two voices, 5/4 and 7/8, one declared motif, one held-note
# crescendo — the smallest piece that exercises every seam, including the
# score/performance split (docs/09).
SMOKE = PieceSpec(
    title="Smoke",
    style_prompt=(
        "A short, dark modal duet for two voices in shifting odd meters. It opens "
        "quietly with a short theme, then returns to that theme an octave lower "
        "underneath a long held note that swells from nothing to full."
    ),
    voices=[
        _voice("soprano", "C4", "G5"),
        _voice("alto", "G3", "C5"),
    ],
    meters_allowed=[FIVE_FOUR, SEVEN_EIGHT],
    key_center="d",
    target_minutes=0.75,
    tempo_bpm=92,
    language="English",
)


SPECS: dict[str, PieceSpec] = {
    "tool-choir": TOOL_CHOIR,
    "fugue": FUGUE,
    "synthwave": SYNTHWAVE,
    "smoke": SMOKE,
}
