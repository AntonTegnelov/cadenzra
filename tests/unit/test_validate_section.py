"""The M1 gate for `validate_section`: cross-voice contracts.

Pure values in, feedback out — these need no compiler, so they assert the
contract ("no parallel fifths under a forbidding policy") rather than any
particular fragment.
"""

from fractions import Fraction

import mido
import pytest

from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.ids import VoiceId
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.structure import DynamicsPlan, MaterialEntry, SectionPlan
from cadenzra.model.style import ParallelsPolicy, StylePack
from cadenzra.verification.midi_analysis import NoteEvent, extract_voice_notes
from cadenzra.verification.section import validate_section

FOUR_FOUR = simple_meter(4, 4)
TICKS = 384


def _section(**overrides: object) -> SectionPlan:
    defaults: dict[str, object] = {
        "section_id": "A",
        "bars": 2,
        "meter": FOUR_FOUR,
        "key": "c major",
        "tempo_bpm": 90,
        "texture": "homophonic",
        "dynamics": DynamicsPlan(start="mf"),
        "active_voices": ["soprano", "bass"],
    }
    return SectionPlan.model_validate(defaults | overrides)


def _style(policy: ParallelsPolicy = "forbid") -> StylePack:
    return StylePack(parallel_fifths_policy=policy)


def _voices(**lines: list[int]) -> dict[VoiceId, list[NoteEvent]]:
    """Build simultaneous quarter-note lines, one per named voice."""
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    for channel, (name, pitches) in enumerate(lines.items()):
        track = mido.MidiTrack()
        track.name = f"staff:{name}"
        midi.tracks.append(track)
        for pitch in pitches:
            track.append(mido.Message("note_on", channel=channel, note=pitch, velocity=90, time=0))
            track.append(
                mido.Message("note_off", channel=channel, note=pitch, velocity=0, time=TICKS)
            )
    return extract_voice_notes(midi)


def _skeleton(*chords: str) -> HarmonicSkeleton:
    return HarmonicSkeleton(
        section_id="A",
        events=[
            HarmonicEvent(offset=Fraction(index, 4), duration=Fraction(1, 4), chord=chord)
            for index, chord in enumerate(chords)
        ],
    )


# An empty skeleton declares no harmony, so the alignment check has nothing to
# say — which isolates the parallel and material-entry contracts below.
NO_HARMONY = HarmonicSkeleton(section_id="A", events=[])


def test_clean_counterpoint_is_accepted() -> None:
    voices = _voices(soprano=[72, 74, 76, 77], bass=[48, 47, 45, 41])

    assert validate_section(voices, _section(), NO_HARMONY, _style()) == []


def test_parallel_fifths_are_caught_and_located() -> None:
    """Both voices are free here, so each is told — the double-fugue autopsy
    found the alphabetical single-target routing starved half of every pair of
    its feedback."""
    voices = _voices(soprano=[curr for curr in (67, 69)], bass=[60, 62])

    feedback = validate_section(voices, _section(), NO_HARMONY, _style())

    assert len(feedback) == 2
    assert {item.voice_id for item in feedback} == {"soprano", "bass"}
    for item in feedback:
        assert "parallel fifths" in item.message
        assert "bar 1, beat 2" in item.message
        assert item.level == "section"
        assert item.section_id == "A"
        assert item.kind == "parallels"
        assert item.voices == ("bass", "soprano")
        assert item.routing == "both-free"
    assert len({item.fingerprint() for item in feedback}) == 1, (
        "one fault, routed twice — not two faults"
    )


def test_parallel_octaves_are_caught() -> None:
    voices = _voices(soprano=[72, 74], bass=[60, 62])

    feedback = validate_section(voices, _section(), NO_HARMONY, _style())

    assert len(feedback) == 2
    assert all("parallel octaves" in item.message for item in feedback)


def test_a_run_of_parallels_is_one_fault_not_one_per_beat() -> None:
    """A five-note parallel passage used to emit four violations — the audit
    measured 207 events collapsing to ~44 passages. One passage, one fault."""
    voices = _voices(
        soprano=[72, 74, 76, 77, 79], bass=[60, 62, 64, 65, 67]
    )

    feedback = validate_section(voices, _section(bars=2), NO_HARMONY, _style())

    assert len(feedback) == 2, "one item per routed voice, not per attack"
    item = feedback[0]
    assert "through" in item.message, "the message names the passage's extent"
    assert item.span is not None
    assert item.span[0] < item.span[1]


def test_the_same_music_passes_when_the_style_allows_parallels() -> None:
    """The checker is driven by data, not by a branch per genre (docs/03)."""
    voices = _voices(soprano=[67, 69], bass=[60, 62])

    assert validate_section(voices, _section(), NO_HARMONY, _style("allow")) == []
    assert validate_section(voices, _section(), NO_HARMONY, _style("encourage")) == []


def test_fifths_approached_by_contrary_motion_are_not_parallels() -> None:
    voices = _voices(soprano=[67, 69], bass=[60, 50])

    assert validate_section(voices, _section(), NO_HARMONY, _style()) == []


def test_a_repeated_fifth_is_not_a_parallel() -> None:
    """Oblique and static motion into a perfect interval is unremarkable."""
    voices = _voices(soprano=[67, 67], bass=[60, 60])

    assert validate_section(voices, _section(), NO_HARMONY, _style()) == []


def test_a_sustained_clash_against_the_chord_is_flagged() -> None:
    """Eb held over a C major chord is a minor third against a major one —
    the kind of bite no extension explains away."""
    voices = _voices(soprano=[75], bass=[60])

    feedback = validate_section(voices, _section(), _skeleton("C"), _style())

    assert len(feedback) == 1
    assert "D#5" in feedback[0].message
    assert "harmony is C" in feedback[0].message
    assert feedback[0].voice_id == "soprano"
    assert feedback[0].kind == "held_tone"


def test_a_flat_key_spells_its_feedback_in_flats() -> None:
    """The double-fugue's immortal violation told a cello that wrote ees' to
    fix a "D#4" — MIDI spelling leaking into the musician surface. In a flat
    key the message speaks flats, and quotes the note as the voice wrote it."""
    voices = _voices(soprano=[75], bass=[60])

    feedback = validate_section(
        voices, _section(key="c minor"), _skeleton("C"), _style()
    )

    assert len(feedback) == 1
    assert "Eb5" in feedback[0].message
    assert "ees''" in feedback[0].message
    assert "D#5" not in feedback[0].message


def test_ordinary_tensions_are_not_treated_as_wrong_notes() -> None:
    """A ninth over a minor chord is colour, not error. docs/01 rules out a
    general music-theory engine, so this check must not legislate taste under
    the cover of arithmetic — it asks only whether the harmony explains the
    pitch at all."""
    ninth = _voices(soprano=[69], bass=[55])

    assert validate_section(ninth, _section(), _skeleton("Gm"), _style()) == []


def test_a_power_chord_lets_the_voices_supply_the_third() -> None:
    """A chord that names no third is not clashing with the one a voice sings;
    that is what the voice is for."""
    third = _voices(soprano=[65], bass=[50])

    assert validate_section(third, _section(), _skeleton("D5"), _style()) == []


def test_a_strict_style_gets_the_narrow_reading() -> None:
    strict = StylePack(dissonance_policy="strict consonance, no non-chord tones")
    ninth = _voices(soprano=[69], bass=[55])

    assert validate_section(ninth, _section(), _skeleton("Gm"), strict)


def test_a_passing_tone_is_not_a_clash() -> None:
    """A non-chord tone that occupies less than half its harmonic event is
    passing, not a wrong note (docs/05)."""
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:soprano"
    midi.tracks.append(track)
    for pitch in (72, 74, 76):
        track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
        track.append(
            mido.Message("note_off", channel=0, note=pitch, velocity=0, time=TICKS // 4)
        )
    skeleton = HarmonicSkeleton(
        section_id="A",
        events=[HarmonicEvent(offset=Fraction(0), duration=Fraction(1, 4), chord="C")],
    )

    assert validate_section(extract_voice_notes(midi), _section(), skeleton, _style()) == []


def test_an_unreadable_chord_symbol_is_reported_not_ignored() -> None:
    voices = _voices(soprano=[72])

    feedback = validate_section(voices, _section(), _skeleton("Cwobble"), _style())

    assert any("not one the harmony checker can read" in item.message for item in feedback)


SUBJECT_PITCHES = [60, 62, 64, 67]


def _subject() -> list[NoteEvent]:
    return _voices(subject=SUBJECT_PITCHES)["subject"]


def _with_entry(relation: str) -> SectionPlan:
    return _section(
        bars=4,
        material=[
            MaterialEntry(motif_id="subject", voice_id="soprano", bar=1, relation=relation)
        ],
    )


def test_a_correct_entry_verifies() -> None:
    voices = _voices(soprano=[pitch + 7 for pitch in SUBJECT_PITCHES])

    feedback = validate_section(
        voices, _with_entry("P5 up"), NO_HARMONY, _style(), {"subject": _subject()}
    )

    assert feedback == []


def test_a_wrong_entry_names_the_voice_and_where_it_departs() -> None:
    voices = _voices(soprano=[67, 69, 72, 74])

    feedback = validate_section(
        voices, _with_entry("P5 up"), NO_HARMONY, _style(), {"subject": _subject()}
    )

    assert len(feedback) == 1
    item = feedback[0]
    assert item.voice_id == "soprano"
    assert "should be subject" in item.message
    assert "bar 1, beat 3" in item.message


def test_an_entry_naming_an_unknown_motif_is_reported() -> None:
    voices = _voices(soprano=SUBJECT_PITCHES)

    feedback = validate_section(voices, _with_entry("exact"), NO_HARMONY, _style(), {})

    assert len(feedback) == 1
    assert "not in the motif library" in feedback[0].message


def test_an_unknown_relation_is_reported_rather_than_silently_passing() -> None:
    voices = _voices(soprano=SUBJECT_PITCHES)

    feedback = validate_section(
        voices, _with_entry("sideways"), NO_HARMONY, _style(), {"subject": _subject()}
    )

    assert len(feedback) == 1
    assert "not one the checker knows" in feedback[0].message


def test_right_notes_with_wrong_rhythm_is_still_a_failed_entry() -> None:
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:soprano"
    midi.tracks.append(track)
    for pitch in SUBJECT_PITCHES:
        track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
        track.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=TICKS * 2))

    feedback = validate_section(
        extract_voice_notes(midi),
        _with_entry("exact"),
        NO_HARMONY,
        _style(),
        {"subject": _subject()},
    )

    assert len(feedback) == 1
    assert "not its rhythm" in feedback[0].message


@pytest.mark.parametrize("relation", ["exact", "P5 up", "octave down", "inversion"])
def test_every_supported_relation_can_verify_a_correct_entry(relation: str) -> None:
    transforms = {
        "exact": SUBJECT_PITCHES,
        "P5 up": [pitch + 7 for pitch in SUBJECT_PITCHES],
        "octave down": [pitch - 12 for pitch in SUBJECT_PITCHES],
        "inversion": [60, 58, 56, 53],
    }
    voices = _voices(soprano=transforms[relation])

    feedback = validate_section(
        voices, _with_entry(relation), NO_HARMONY, _style(), {"subject": _subject()}
    )

    assert feedback == []


def test_a_rhythm_mismatch_says_which_rhythm_is_needed() -> None:
    """"Not its rhythm" is not actionable; naming the note values is. Same
    reasoning as naming the target pitch of a transposed entry rather than
    asking the model to work it out."""
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:soprano"
    midi.tracks.append(track)
    for pitch in SUBJECT_PITCHES:
        track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
        track.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=TICKS * 2))

    feedback = validate_section(
        extract_voice_notes(midi),
        _with_entry("exact"),
        NO_HARMONY,
        _style(),
        {"subject": _subject()},
    )

    assert len(feedback) == 1
    assert "needs the durations 4 4 4 4" in feedback[0].message
    assert "and has 2 2 2 2" in feedback[0].message


# --- routing around prescribed entries -------------------------------------
#
# The double-fugue autopsy, mechanism 2c/2d: every pair violation went to the
# alphabetically-first voice, which in a fugue exposition is routinely the one
# whose bars the entry check pins note-for-note. The router must never ask a
# prescribed voice to move, and must go loud when nobody can.

UPPER_LINE = [72, 74, 76, 77]
LOWER_LINE = [60, 62, 64, 65]  # parallel octaves against UPPER_LINE throughout


def _both_lines() -> dict[VoiceId, list[NoteEvent]]:
    return _voices(soprano=UPPER_LINE, bass=LOWER_LINE)


def _motifs() -> dict[str, list[NoteEvent]]:
    return {
        "upper_subject": _voices(m=UPPER_LINE)["m"],
        "lower_subject": _voices(m=LOWER_LINE)["m"],
    }


def test_a_pair_violation_routes_to_the_free_voice_not_the_alphabetical_one() -> None:
    """The bass is prescribed here; blaming it anyway (the old alphabetical
    rule) asks a voice that cannot move to fix the relationship."""
    section = _section(
        bars=4,
        material=[
            MaterialEntry(motif_id="lower_subject", voice_id="bass", bar=1, relation="exact")
        ],
    )

    feedback = validate_section(
        _both_lines(), section, NO_HARMONY, _style(), _motifs()
    )

    parallels = [item for item in feedback if item.kind == "parallels"]
    assert len(parallels) == 1
    assert parallels[0].voice_id == "soprano"
    assert parallels[0].routing == "only-free-voice"


def test_a_clash_between_two_prescribed_lines_goes_loud_not_to_a_voice() -> None:
    """When both lines are pinned by entries, no voice-level repair exists —
    the plan owns the contradiction. The item says so instead of burning the
    section budget on an impossible fix."""
    section = _section(
        bars=4,
        material=[
            MaterialEntry(motif_id="upper_subject", voice_id="soprano", bar=1, relation="exact"),
            MaterialEntry(motif_id="lower_subject", voice_id="bass", bar=1, relation="exact"),
        ],
    )

    feedback = validate_section(
        _both_lines(), section, NO_HARMONY, _style(), _motifs()
    )

    parallels = [item for item in feedback if item.kind == "parallels"]
    assert len(parallels) == 1
    assert parallels[0].voice_id is None
    assert parallels[0].routing == "unfixable"
    assert parallels[0].voices == ("bass", "soprano")


def test_a_held_clash_inside_a_prescribed_entry_is_unfixable_at_voice_level() -> None:
    """The immortal D#4: the subject itself clashing with the grid. Routing it
    to the voice spent three sweeps not fixing it."""
    section = _section(
        bars=4,
        material=[
            MaterialEntry(motif_id="upper_subject", voice_id="soprano", bar=1, relation="exact")
        ],
    )
    # Eb (75) is not in C; the soprano's first note is prescribed by its entry.
    # The bass stays on chord tones so the only clash is the prescribed one.
    voices = _voices(soprano=[75, 74, 76, 77], bass=[48, 52, 55, 48])
    motifs = {"upper_subject": _voices(m=[75, 74, 76, 77])["m"]}

    feedback = validate_section(
        voices, section, _skeleton("C", "C", "C", "C"), _style("allow"), motifs
    )

    held = [item for item in feedback if item.kind == "held_tone"]
    assert len(held) == 1
    assert held[0].voice_id is None
    assert held[0].routing == "unfixable"
    assert "soprano" in held[0].message


def test_entry_spans_cover_the_motif_from_its_entry_bar() -> None:
    from cadenzra.verification.section import entry_spans

    section = _section(
        bars=4,
        material=[
            MaterialEntry(motif_id="upper_subject", voice_id="soprano", bar=2, relation="exact")
        ],
    )

    spans = entry_spans(section, _motifs())

    assert list(spans) == ["soprano"]
    ((start, end),) = spans["soprano"]
    assert start == Fraction(1)  # bar 2 of 4/4
    assert end == Fraction(2)  # four quarters long
