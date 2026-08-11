"""Contracts for MIDI analysis, material relations, scaffolding, and chords.

These are the pure layer that carries the correctness guarantees, so they are
tested as values-in/values-out with hand-built MIDI — no compiler, no fixtures
beyond what a test can construct.
"""

from fractions import Fraction

import mido
import pytest

from cadenzra.model.primitives.meter import MeterSpec, MeterTerm, simple_meter
from cadenzra.notation.chords import ChordSymbolError, parse_chord_symbol
from cadenzra.notation.scaffold import (
    bar_of_fragment_line,
    bar_of_fragment_position,
    lily_time_command,
    scaffold_fragment,
)
from cadenzra.verification.midi_analysis import (
    NoteEvent,
    channel_track_invariant_ok,
    extract_voice_notes,
    extract_voice_tracks,
    notes_in_span,
    notes_sounding_at,
    within_tolerance,
)
from cadenzra.verification.transposition import (
    UnknownRelationError,
    interval_sequence,
    intervals_match_under_relation,
    parse_relation,
    rhythm_profile_matches,
    transpose_semitones,
)

TICKS = 384  # per quarter note


def _midi(*voices: tuple[str, int, list[tuple[int, int, int]]]) -> mido.MidiFile:
    """Build a MIDI file from (name, channel, [(pitch, start_tick, length)])."""
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    for name, channel, notes in voices:
        track = mido.MidiTrack()
        track.name = name
        midi.tracks.append(track)
        events: list[tuple[int, mido.Message]] = []
        for pitch, start, length in notes:
            events.append(
                (start, mido.Message("note_on", channel=channel, note=pitch, velocity=90))
            )
            events.append(
                (
                    start + length,
                    mido.Message("note_off", channel=channel, note=pitch, velocity=0),
                )
            )
        events.sort(key=lambda pair: pair[0])
        tick = 0
        for absolute, message in events:
            track.append(message.copy(time=absolute - tick))
            tick = absolute
    return midi


def _line(pitches: list[int], *, channel: int = 0, step: int = TICKS) -> list[tuple[int, int, int]]:
    return [(pitch, index * step, step) for index, pitch in enumerate(pitches)]


def test_notes_are_positioned_in_whole_notes_from_the_start() -> None:
    midi = _midi(("staff:soprano", 0, _line([60, 62, 64, 65])))

    notes = extract_voice_notes(midi)["soprano"]

    assert [note.onset for note in notes] == [
        Fraction(0),
        Fraction(1, 4),
        Fraction(1, 2),
        Fraction(3, 4),
    ]
    assert all(note.duration == Fraction(1, 4) for note in notes)


def test_voices_are_keyed_by_name_not_by_channel_order() -> None:
    """Channels are distinct but not contiguous, so their order means nothing
    — the track name is the reliable key (docs/03, M0 empirical answer)."""
    midi = _midi(
        ("staff:soprano", 0, _line([72])),
        ("staff:alto", 2, _line([67])),
        ("staff:bass", 4, _line([48])),
    )

    tracks = {track.voice_id: track.channel for track in extract_voice_tracks(midi)}

    assert tracks == {"soprano": 0, "alto": 2, "bass": 4}
    assert channel_track_invariant_ok(midi)


def test_a_voice_spanning_two_channels_is_a_broken_invariant() -> None:
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:mixed"
    midi.tracks.append(track)
    for channel in (0, 1):
        track.append(mido.Message("note_on", channel=channel, note=60, velocity=90, time=0))
        track.append(mido.Message("note_off", channel=channel, note=60, velocity=0, time=TICKS))

    with pytest.raises(ValueError, match="one voice must be one track"):
        extract_voice_tracks(midi)
    assert not channel_track_invariant_ok(midi)


def test_two_voices_sharing_a_channel_break_the_invariant() -> None:
    midi = _midi(("staff:soprano", 0, _line([72])), ("staff:alto", 0, _line([60])))

    assert not channel_track_invariant_ok(midi)


def test_empty_and_lyric_tracks_are_not_voices() -> None:
    midi = _midi(("staff:soprano", 0, _line([60])), ("", 0, []))

    assert [track.voice_id for track in extract_voice_tracks(midi)] == ["soprano"]


def test_a_quarter_tone_note_keeps_its_bend() -> None:
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:solo"
    midi.tracks.append(track)
    track.append(mido.Message("pitchwheel", channel=0, pitch=2048, time=0))
    track.append(mido.Message("note_on", channel=0, note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=TICKS))

    assert extract_voice_notes(midi)["solo"][0].bend == 2048


def test_tolerance_accepts_tuplet_rounding_but_not_a_wrong_note_value() -> None:
    assert within_tolerance(Fraction(1, 3), Fraction(1, 3) + Fraction(1, 384))
    assert not within_tolerance(Fraction(1, 4), Fraction(1, 8))


def test_sounding_and_span_queries_pick_the_right_notes() -> None:
    notes = extract_voice_notes(_midi(("staff:v", 0, _line([60, 62, 64, 65]))))["v"]

    assert [n.midi_pitch for n in notes_sounding_at(notes, Fraction(1, 4))] == [62]
    assert [n.midi_pitch for n in notes_in_span(notes, Fraction(0), Fraction(1, 2))] == [60, 62]


SUBJECT = [60, 62, 64, 67, 65]


def _notes(pitches: list[int]) -> list[NoteEvent]:
    return extract_voice_notes(_midi(("staff:v", 0, _line(pitches))))["v"]


def test_interval_sequence_is_what_transposition_preserves() -> None:
    assert interval_sequence(_notes(SUBJECT)) == [2, 2, 3, -2]
    assert interval_sequence(transpose_semitones(_notes(SUBJECT), 7)) == [2, 2, 3, -2]


@pytest.mark.parametrize(
    ("text", "kind", "semitones"),
    [
        ("exact", "exact", 0),
        ("P5 up", "transposition", 7),
        ("P5 below", "transposition", -7),
        ("octave down", "transposition", -12),
        ("M3 up", "transposition", 4),
        ("real answer", "transposition", 7),
        ("inversion", "inversion", 0),
        ("tonal answer", "tonal answer", 0),
    ],
)
def test_the_relation_vocabulary_parses(text: str, kind: str, semitones: int) -> None:
    relation = parse_relation(text)

    assert relation.kind == kind
    assert relation.semitones == semitones


@pytest.mark.parametrize("text", ["", "sideways", "P9 up", "up P5", "P5"])
def test_an_unknown_relation_raises_rather_than_verifying_nothing(text: str) -> None:
    with pytest.raises(UnknownRelationError):
        parse_relation(text)


def test_an_exact_transposition_of_the_subject_verifies() -> None:
    entry = _notes([pitch + 7 for pitch in SUBJECT])

    result = intervals_match_under_relation(_notes(SUBJECT), entry, parse_relation("P5 up"))

    assert result.ok


def test_one_wrong_note_fails_and_names_where() -> None:
    wrong = [60 + 7, 62 + 7, 65 + 7, 67 + 7, 65 + 7]

    result = intervals_match_under_relation(
        _notes(SUBJECT), _notes(wrong), parse_relation("P5 up")
    )

    assert not result.ok
    assert result.first_deviation_index == 2
    assert result.first_deviation_offset == Fraction(1, 2)


def test_an_inversion_verifies_against_the_inverted_contour() -> None:
    inverted = [60, 58, 56, 53, 55]

    assert intervals_match_under_relation(
        _notes(SUBJECT), _notes(inverted), parse_relation("inversion")
    ).ok


def test_an_entry_of_the_wrong_length_fails() -> None:
    result = intervals_match_under_relation(
        _notes(SUBJECT), _notes(SUBJECT[:3]), parse_relation("exact")
    )

    assert not result.ok
    assert "3 notes" in result.detail


def test_a_real_tonal_answer_passes_where_a_strict_check_would_not() -> None:
    """The classic adjustment: one note of the answer is pulled a scale degree
    to stay in the key, and the rest transposes literally. Note that a single
    adjusted *note* moves two *intervals* — which is why the tolerance is
    stated per note."""
    answer = [67, 68, 71, 74, 72]  # a literal fifth up would be 67 69 71 74 72

    strict = intervals_match_under_relation(
        _notes(SUBJECT), _notes(answer), parse_relation("P5 up")
    )
    tonal = intervals_match_under_relation(
        _notes(SUBJECT), _notes(answer), parse_relation("tonal answer")
    )

    assert not strict.ok
    assert tonal.ok


def test_an_answer_that_reverses_contour_is_not_an_answer() -> None:
    """Contour is not implied by the step tolerance: a two-semitone nudge can
    still flip a semitone interval, so it is checked outright."""
    chromatic_subject = _notes([60, 61, 64, 67, 65])
    reversed_opening = _notes([67, 66, 71, 74, 72])

    result = intervals_match_under_relation(
        chromatic_subject, reversed_opening, parse_relation("tonal answer")
    )

    assert not result.ok
    assert "contour" in result.detail


def test_an_answer_that_adjusts_everything_is_a_different_subject() -> None:
    drifted = [67, 70, 73, 75, 74]

    result = intervals_match_under_relation(
        _notes(SUBJECT), _notes(drifted), parse_relation("tonal answer")
    )

    assert not result.ok
    assert "notes differ" in result.detail


def test_a_leap_sized_deviation_is_never_a_tonal_adjustment() -> None:
    leapt = [67, 73, 71, 74, 72]

    result = intervals_match_under_relation(
        _notes(SUBJECT), _notes(leapt), parse_relation("tonal answer")
    )

    assert not result.ok
    assert "not a leap" in result.detail


def test_rhythm_must_survive_the_entry_too() -> None:
    same = _notes([pitch + 7 for pitch in SUBJECT])
    stretched = extract_voice_notes(
        _midi(("staff:v", 0, _line([p + 7 for p in SUBJECT], step=TICKS * 2)))
    )["v"]

    assert rhythm_profile_matches(_notes(SUBJECT), same)
    assert not rhythm_profile_matches(_notes(SUBJECT), stretched)


SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
ADDITIVE = MeterSpec(
    terms=[MeterTerm(numerator=3, denominator=4), MeterTerm(numerator=1, denominator=8)]
)


@pytest.mark.parametrize(
    ("meter", "command"),
    [
        (simple_meter(4, 4), "\\time 4/4"),
        (SEVEN_EIGHT, "\\time #'(2 2 3) 7/8"),
        (ADDITIVE, "\\timeAbbrev #'((3 4) (1 8))"),
    ],
)
def test_meters_render_as_the_2_26_syntax(meter: MeterSpec, command: str) -> None:
    assert lily_time_command(meter) == command


def test_a_scaffold_locates_the_fragment_inside_itself() -> None:
    fragment = "c'4 d' e' f' |\ng'4 a' b' c'' |"

    scaffolded = scaffold_fragment(fragment, simple_meter(4, 4))

    lines = scaffolded.source.split("\n")
    assert lines[scaffolded.first_fragment_line - 1] == "c'4 d' e' f' |"
    assert scaffolded.fragment_line_of(scaffolded.first_fragment_line + 1) == 2


FRAGMENT = "c'4 d' e' f' |\ng'4 a' b' c'' |\nd''4 c'' b' a' |"


@pytest.mark.parametrize(("line", "bar"), [(1, 1), (2, 2), (3, 3)])
def test_bar_numbers_come_from_counting_bar_checks(line: int, bar: int) -> None:
    assert bar_of_fragment_line(FRAGMENT, line) == bar


def test_a_warning_at_a_barline_belongs_to_the_bar_it_closes() -> None:
    """LilyPond points at the bar check itself, in 1-based columns, when a bar
    does not fill. Line 2 of the fixture is `g'4 a' b' c'' |`, so its bar check
    is column 15 and that failure belongs to bar 2."""
    assert bar_of_fragment_position(FRAGMENT, 2, column=15) == 2
    assert bar_of_fragment_position(FRAGMENT, 2, column=16) == 3


def test_bar_counting_ignores_barlines_inside_strings() -> None:
    fragment = 'c\'4 d\' e\' f\' |\n\\bar "||"\ng\'4 a\' b\' c\'\' |'

    assert bar_of_fragment_line(fragment, 3) == 2


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("C", {0, 4, 7}),
        ("Dm", {2, 5, 9}),
        ("D5", {2, 9}),
        ("Esus4", {4, 9, 11}),
        ("F#m7", {6, 9, 1, 4}),
        ("Bbmaj7", {10, 2, 5, 9}),
        ("Gdim7", {7, 10, 1, 4}),
        ("Am7b5", {9, 0, 3, 7}),
    ],
)
def test_chord_symbols_reduce_to_pitch_class_sets(symbol: str, expected: set[int]) -> None:
    assert set(parse_chord_symbol(symbol).pitch_classes) == expected


def test_a_slash_chord_adds_its_bass() -> None:
    chord = parse_chord_symbol("Esus4/B")

    assert chord.bass_pc == 11
    assert chord.contains(11)


@pytest.mark.parametrize("symbol", ["", "H", "Cwobble", "C/H", "7"])
def test_an_unparseable_symbol_raises(symbol: str) -> None:
    with pytest.raises(ChordSymbolError):
        parse_chord_symbol(symbol)


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("Dm(b9)", {2, 5, 9, 3}),
        ("C7#11", {0, 4, 7, 10, 6}),
        ("Cmaj7(9)", {0, 4, 7, 11, 2}),
        ("Cadd9", {0, 2, 4, 7}),
    ],
)
def test_altered_and_added_tones_widen_the_chord(symbol: str, expected: set[int]) -> None:
    """Models reach for these constantly. Rejecting them costs a whole
    regeneration round trip for a chord the checker could have understood, and
    an added ninth only makes the alignment check *more* permissive — which is
    the honest reading of what the symbol asked for."""
    assert set(parse_chord_symbol(symbol).pitch_classes) == expected


def test_a_quality_that_looks_like_an_alteration_is_not_taken_apart() -> None:
    """`m7b5` is half-diminished, not a minor seventh with an added flat five."""
    chord = parse_chord_symbol("Am7b5")

    assert chord.quality == "m7b5"
    assert set(chord.pitch_classes) == {9, 0, 3, 7}


def test_a_genuinely_unknown_alteration_still_raises() -> None:
    with pytest.raises(ChordSymbolError):
        parse_chord_symbol("C(banana)")


def test_suspended_and_extended_qualities_the_probe_pieces_asked_for() -> None:
    """A late-Romantic orchestral run wrote Bb9sus4 and the parser had never
    heard of it, which bounced a whole section's harmony."""
    assert parse_chord_symbol("Bb9sus4").pitch_classes == frozenset({10, 0, 3, 5, 8})
    assert parse_chord_symbol("G7sus2").pitch_classes == frozenset({7, 9, 2, 5})
    assert parse_chord_symbol("Am11").pitch_classes == frozenset({9, 11, 0, 2, 4, 7})


def test_the_jazz_vocabulary_the_game_score_run_asked_for() -> None:
    """A Collier-flavored harmony brief wrote Dm(maj9)/D, D7(sus4,b9)/D,
    A7alt/D and A13sus4/D, and each bounced a whole section's harmony."""
    assert parse_chord_symbol("Dm(maj9)/D").pitch_classes == frozenset({2, 5, 9, 1, 4})
    assert parse_chord_symbol("D7(sus4,b9)/D").pitch_classes == frozenset(
        {2, 6, 9, 0, 7, 3}
    )
    assert parse_chord_symbol("A7alt/D").pitch_classes == frozenset(
        {9, 10, 0, 1, 2, 3, 5, 7}
    )
    assert parse_chord_symbol("A13sus4/D").pitch_classes == frozenset({9, 11, 2, 4, 6, 7})
    assert parse_chord_symbol("G7(alt)").pitch_classes == frozenset(
        {7, 11, 2, 5, 8, 10, 1, 3}
    )
    assert parse_chord_symbol("Faug7(b9)/D").pitch_classes == frozenset(
        {5, 9, 1, 3, 6, 2}
    )


def test_a_slash_is_always_a_bass_note() -> None:
    """Which is why there is no 6/9: it cannot be told apart from a C6 over a
    bass, so the spelling would be an entry nothing could reach."""
    assert parse_chord_symbol("Bb/D").bass_pc == 2
