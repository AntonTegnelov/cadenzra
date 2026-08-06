"""The specs the project is verified against, as data.

Style enters the system as data and never as code, so these are just values —
a Tool-inspired choir piece, a fugue, and something deliberately unlike either.
Three genuinely different styles going through unchanged pipeline code is what
"genre-general" means operationally (docs/01, success criterion 4).
"""

from cadenzra.model.primitives.meter import MeterSpec, simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import LyricsSpec, PieceSpec, VoiceSpec

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
    lyrics=LyricsSpec(
        language="English",
        brief=(
            "A vessel that carries something it cannot name, and empties. Concrete "
            "and physical rather than abstract — water, weight, hollowness, the "
            "sound a held container makes. It should read as one thought moving "
            "from near-silence to something overwhelming and back."
        ),
        devices=["objective_correlative", "anaphora", "polyptoton"],
    ),
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
    lyrics=LyricsSpec(
        language="English",
        brief="smoke rising off water at first light, and thinning to nothing",
    ),
)

# --- the quality probes -----------------------------------------------
#
# Nine pieces chosen to fail in different ways: restraint, compression,
# duration, ensemble size, contrapuntal difficulty, lyric density, and two
# idioms a long way from the training gravity of notated art music — plus
# their fusion. What each one is for is recorded in
# `docs/harness-results/quality-review.md`.

THREE_FOUR: MeterSpec = simple_meter(3, 4)
ELEVEN_EIGHT: MeterSpec = simple_meter(11, 8, [3, 3, 3, 2])

MINIMAL = PieceSpec(
    title="Slow Machine",
    style_prompt=(
        "Minimalist process music for two pianos in the manner of Glass and "
        "Pärt: a short cell that repeats with one small change at a time, long "
        "stretches of near-stillness, consonant diatonic harmony that shifts "
        "only occasionally. Silence and repetition are the material — resist "
        "adding incident. The interest comes from how slowly it changes."
    ),
    voices=[
        _voice("piano_right", "C4", "C6", program=0, lyrics=False),
        _voice("piano_left", "C2", "C4", program=0, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR, THREE_FOUR],
    key_center="a",
    target_minutes=2.0,
    tempo_bpm=72,
)

MINIATURE = PieceSpec(
    title="One Minute",
    style_prompt=(
        "A one-minute art song for solo voice and piano — a complete miniature, "
        "not an excerpt. It needs a beginning, a turn, and an ending inside "
        "sixty seconds: a single sung phrase that opens, one that answers it "
        "differently, and a close that settles. Intimate and unhurried despite "
        "the length."
    ),
    voices=[
        _voice("voice", "A3", "F5"),
        _voice("piano", "C2", "C6", program=0, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR, THREE_FOUR],
    key_center="f",
    target_minutes=1.0,
    tempo_bpm=66,
    lyrics=LyricsSpec(
        language="English",
        brief="a single held moment before leaving a house for the last time",
        rhyme_scheme="ABAB",
    ),
)

LONGFORM = PieceSpec(
    title="The Long Field",
    style_prompt=(
        "A ten-minute work for string orchestra in five connected movements, "
        "played without a break. One theme, transformed across all five: stated "
        "plainly, fragmented, inverted under a faster surface, brought back "
        "slowly in the wrong key, and resolved. The piece has to feel like one "
        "argument sustained over ten minutes, not five short pieces."
    ),
    voices=[
        _voice("violin1", "G3", "E6", program=48, lyrics=False, group="upper"),
        _voice("violin2", "G3", "C6", program=48, lyrics=False, group="upper"),
        _voice("viola", "C3", "E5", program=48, lyrics=False, group="middle"),
        _voice("cello", "C2", "G4", program=48, lyrics=False, group="lower"),
        _voice("bass", "E1", "G3", program=43, lyrics=False, group="lower"),
    ],
    meters_allowed=[FOUR_FOUR, THREE_FOUR, FIVE_FOUR, SIX_EIGHT],
    key_center="e",
    target_minutes=10.0,
    tempo_bpm=76,
)

ORCHESTRA = PieceSpec(
    title="Ascent",
    style_prompt=(
        "A late-Romantic orchestral movement: full winds, brass, and strings "
        "building from a single low line to a full-orchestra climax and "
        "subsiding. Idiomatic writing for each family — sustained brass chorale, "
        "woodwind figuration over string tremolo, doubling at the octave where "
        "it adds weight. The orchestration is the argument."
    ),
    voices=[
        _voice("flute", "C4", "C7", program=73, lyrics=False, group="winds"),
        _voice("oboe", "A3", "G6", program=68, lyrics=False, group="winds"),
        _voice("clarinet", "D3", "C6", program=71, lyrics=False, group="winds"),
        _voice("bassoon", "B1", "E5", program=70, lyrics=False, group="winds"),
        _voice("horn", "B1", "F5", program=60, lyrics=False, group="brass"),
        _voice("trumpet", "E3", "C6", program=56, lyrics=False, group="brass"),
        _voice("trombone", "E2", "F4", program=57, lyrics=False, group="brass"),
        _voice("violin1", "G3", "E6", program=48, lyrics=False, group="strings"),
        _voice("violin2", "G3", "C6", program=48, lyrics=False, group="strings"),
        _voice("viola", "C3", "E5", program=48, lyrics=False, group="strings"),
        _voice("cello", "C2", "G4", program=48, lyrics=False, group="strings"),
        _voice("contrabass", "E1", "G3", program=43, lyrics=False, group="strings"),
    ],
    meters_allowed=[FOUR_FOUR, THREE_FOUR],
    key_center="ees",
    target_minutes=3.0,
    tempo_bpm=69,
)

DOUBLE_FUGUE = PieceSpec(
    title="Double Fugue in C minor",
    style_prompt=(
        "A double fugue for four-voice string quartet. Two subjects: the first "
        "long-breathed and stepwise, the second short and angular, each with a "
        "complete exposition of its own — every voice entering in turn, answers "
        "at the fifth. Then the two subjects combined in invertible "
        "counterpoint, a stretto where entries overlap, and a final statement "
        "of both over a dominant pedal."
    ),
    voices=[
        _voice("violin1", "G3", "E6", program=40, lyrics=False, group="upper"),
        _voice("violin2", "G3", "C6", program=40, lyrics=False, group="upper"),
        _voice("viola", "C3", "E5", program=41, lyrics=False, group="lower"),
        _voice("cello", "C2", "G4", program=42, lyrics=False, group="lower"),
    ],
    meters_allowed=[FOUR_FOUR],
    key_center="c",
    target_minutes=3.0,
    tempo_bpm=84,
)

DENSE_LYRICS = PieceSpec(
    title="Gallery of Salt",
    style_prompt=(
        "An art-pop song for two voices and rhythm section, rhythmically "
        "intricate and word-driven: the vocal line exists to carry a dense "
        "text, with syncopations that push against the beat, and space where "
        "the words need it."
    ),
    voices=[
        _voice("lead", "G3", "E5"),
        _voice("harmony", "C3", "A4"),
        _voice("keys", "C2", "C6", program=4, lyrics=False),
        _voice("bass", "E1", "G3", program=33, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR, SEVEN_EIGHT],
    key_center="b",
    target_minutes=2.5,
    tempo_bpm=96,
    lyrics=LyricsSpec(
        language="English",
        brief=(
            "Someone walks through a museum of things preserved in salt and "
            "recognizes one of them. The text should be dense and worked: "
            "rhymes arriving inside lines as often as at their ends, sound "
            "chosen as carefully as sense, and the stresses deliberately "
            "fighting the beat where the meaning turns."
        ),
        rhyme_scheme="AABB",
        devices=[
            "prosodic_dissonance",
            "melopoeia",
            "mosaic_rhyme",
            "ekphrasis",
            "internal_rhyme",
            "polyptoton",
        ],
    ),
)

METAL = PieceSpec(
    title="Iron Liturgy",
    style_prompt=(
        "Riff-driven metal for two guitars, bass and a sung vocal. Palm-muted "
        "low-register riffs in tight rhythmic unison, modal and chromatic "
        "rather than functional, tempo and meter shifts between sections, a "
        "half-time breakdown, and a harmonized twin-guitar lead. Weight and "
        "repetition over melody."
    ),
    voices=[
        _voice("vocal", "E3", "E5"),
        _voice("guitar1", "E2", "E5", program=30, lyrics=False, group="guitars"),
        _voice("guitar2", "E2", "E5", program=30, lyrics=False, group="guitars"),
        _voice("bass", "E1", "E3", program=33, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR, SEVEN_EIGHT, ELEVEN_EIGHT],
    key_center="e",
    target_minutes=2.5,
    tempo_bpm=138,
    lyrics=LyricsSpec(
        language="English",
        brief="a machine that is worshipped by the people it consumes",
        devices=["anaphora", "objective_correlative"],
    ),
)

KPOP = PieceSpec(
    title="Neon Hours",
    style_prompt=(
        "A K-pop song: bright synth-pop with a clear intro, verse, pre-chorus "
        "that lifts, an unmissable chorus hook that returns identically, a "
        "contrasting bridge, and a final chorus. Two vocal parts trading lines "
        "in the verses and singing together in the chorus. Clean major-key "
        "harmony with a couple of borrowed chords, and a hook that survives "
        "being repeated."
    ),
    voices=[
        _voice("vocal1", "A3", "E5"),
        _voice("vocal2", "F3", "C5"),
        _voice("synth", "C3", "C6", program=81, lyrics=False),
        _voice("bass", "E1", "G3", program=38, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR],
    key_center="a",
    target_minutes=2.5,
    tempo_bpm=124,
    lyrics=LyricsSpec(
        language="English",
        brief="staying out all night in a city that never turns its lights off",
        rhyme_scheme="AABB",
        devices=["refrain", "anaphora"],
    ),
)

METAL_KPOP = PieceSpec(
    title="Chrome Teeth",
    style_prompt=(
        "A genuine fusion of metal and K-pop, not an alternation between them: "
        "downtuned palm-muted riffs carrying pop chord motion, a chorus hook "
        "that is both singable and heavy, verses where a clean pop vocal sits "
        "over a metal rhythm section, and a breakdown that keeps the hook "
        "audible underneath it. Both idioms present at once in every section."
    ),
    voices=[
        _voice("vocal1", "A3", "E5"),
        _voice("vocal2", "E3", "B4"),
        _voice("guitar", "E2", "E5", program=30, lyrics=False),
        _voice("synth", "C3", "C6", program=81, lyrics=False),
        _voice("bass", "E1", "E3", program=33, lyrics=False),
    ],
    meters_allowed=[FOUR_FOUR, SEVEN_EIGHT],
    key_center="fis",
    target_minutes=2.5,
    tempo_bpm=132,
    lyrics=LyricsSpec(
        language="English",
        brief="loving something that is visibly bad for you, and choosing it anyway",
        rhyme_scheme="ABAB",
        devices=["refrain", "polyptoton", "internal_rhyme"],
    ),
)


SPECS: dict[str, PieceSpec] = {
    "tool-choir": TOOL_CHOIR,
    "fugue": FUGUE,
    "synthwave": SYNTHWAVE,
    "smoke": SMOKE,
    "minimal": MINIMAL,
    "miniature": MINIATURE,
    "longform": LONGFORM,
    "orchestra": ORCHESTRA,
    "double-fugue": DOUBLE_FUGUE,
    "dense-lyrics": DENSE_LYRICS,
    "metal": METAL,
    "kpop": KPOP,
    "metal-kpop": METAL_KPOP,
}
