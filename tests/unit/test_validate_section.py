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
    """One fault, one moving line. Both-told routing was the fix for repairs
    against stale snapshots; with sequential repairs the second telling only
    doubled the churn — every pair edited both its voices per sweep, and the
    sweep equilibrium sat at ~70 faults while repairs re-injected as many
    parallels as they fixed. The un-told voice anchors."""
    voices = _voices(soprano=[curr for curr in (67, 69)], bass=[60, 62])

    feedback = validate_section(voices, _section(), NO_HARMONY, _style())

    assert len(feedback) == 1
    (item,) = feedback
    assert item.voice_id == "soprano", "deterministic: the later-sorted voice moves"
    assert "parallel fifths" in item.message
    assert "bar 1, beat 2" in item.message
    assert item.level == "section"
    assert item.section_id == "A"
    assert item.kind == "parallels"
    assert item.voices == ("bass", "soprano")
    assert item.routing == "both-free"
    assert item.span == (Fraction(0), Fraction(1, 4)), (
        "the approach is part of the passage: a live loop died on one "
        "'into the downbeat' fault whose fix lived in the bar before, "
        "which the patch was never offered"
    )


def test_parallels_name_the_colliding_notes() -> None:
    """The message hands over the simultaneities, not just the passage.

    The measured tail fix rate said the patcher mostly could not extract
    the colliding notes from the sibling line itself — a converging live
    loop ground down at ~1 fault per sweep and hit the budget. The
    arithmetic was already computed; the message must not discard it.
    """
    voices = _voices(soprano=[67, 69], bass=[60, 62])

    (item,) = validate_section(voices, _section(), NO_HARMONY, _style())

    assert "bar 1, beat 1: c' against g'" in item.message, (
        "pitch order matches the name order in 'bass and soprano'"
    )
    assert "bar 1, beat 2: d' against a'" in item.message
    assert "change one of the named notes" in item.message


def test_parallel_octaves_are_caught() -> None:
    voices = _voices(soprano=[72, 74], bass=[60, 62])

    feedback = validate_section(voices, _section(), NO_HARMONY, _style())

    assert len(feedback) == 1
    assert all("parallel octaves" in item.message for item in feedback)


def test_a_run_of_parallels_is_one_fault_not_one_per_beat() -> None:
    """A five-note parallel passage used to emit four violations — the audit
    measured 207 events collapsing to ~44 passages. One passage, one fault."""
    voices = _voices(
        soprano=[72, 74, 76, 77, 79], bass=[60, 62, 64, 65, 67]
    )

    feedback = validate_section(voices, _section(bars=2), NO_HARMONY, _style())

    assert len(feedback) == 1, "one passage, one routed voice, not one per attack"
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


def test_parallels_are_judged_between_beats_not_ornaments() -> None:
    """61 of a live run's 101 parallel items involved sub-beat attacks —
    passing eighths whose coincidence is diminution, not voice-leading. The
    rule is judged between attacks that land on beats, the same definitional
    scoping "held" got: a genuine parallel eighth-run still lands fifths on
    consecutive beats and is still caught."""
    from fractions import Fraction as F

    def _line(notes: list[tuple[int, F, F]]) -> list[NoteEvent]:
        return [
            NoteEvent(
                midi_pitch=pitch, onset=onset, duration=dur, velocity=90, channel=0
            )
            for pitch, onset, dur in notes
        ]

    eighth, quarter = F(1, 8), F(1, 4)
    four_four = simple_meter(4, 4)
    # Off-beat slip: a fourth on the beat, fifths only at the off-beat and the
    # next beat — one ornamental coincidence, not a parallel pair of beats.
    slip_upper = _line([(65, F(0), eighth), (69, eighth, eighth), (71, quarter, quarter)])
    slip_lower = _line([(60, F(0), eighth), (62, eighth, eighth), (64, quarter, quarter)])
    # True parallel run: fifths on consecutive beats, eighths in between.
    run_upper = _line([(67, F(0), eighth), (69, eighth, eighth), (71, quarter, quarter)])
    run_lower = _line([(60, F(0), eighth), (62, eighth, eighth), (64, quarter, quarter)])

    slip = validate_section(
        {"soprano": slip_upper, "bass": slip_lower},
        _section(meter=four_four),
        NO_HARMONY,
        _style(),
    )
    caught = validate_section(
        {"soprano": run_upper, "bass": run_lower},
        _section(meter=four_four),
        NO_HARMONY,
        _style(),
    )

    assert slip == [], "an off-beat coincidence is diminution"
    assert len(caught) == 1 and caught[0].kind == "parallels"


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
    # The resolution is arithmetic the checker can do exactly: name the
    # steps that land on the chord instead of leaving "resolve by step" as
    # a puzzle — a live fault survived three sweeps of blind sampling.
    assert "D5" in feedback[0].message or "E5" in feedback[0].message


def test_a_passing_eighth_is_not_a_held_tone() -> None:
    """C1's grids died to an inverted subject's eighth-note E4: the chord
    under it was asked to contain Ab, C and E at once, six attempts running.
    An eighth is embellishment, not a held tone — a note counts as held only
    when it overlaps the chord for at least a beat, however short the chord,
    so a finer chord rhythm cannot make the check stricter."""
    def _note(duration: Fraction) -> list[NoteEvent]:
        return [
            NoteEvent(
                midi_pitch=75,
                onset=Fraction(0),
                duration=duration,
                velocity=90,
                channel=0,
            )
        ]

    passing = validate_section(
        {"soprano": _note(Fraction(1, 8))}, _section(), _skeleton("C"), _style()
    )
    sustained = validate_section(
        {"soprano": _note(Fraction(1, 4))}, _section(), _skeleton("C"), _style()
    )

    assert passing == [], "an eighth over a beat-long chord is a passing tone"
    assert [item.kind for item in sustained] == ["held_tone"]


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
    assert "first diverge at bar 1, beat 1" in feedback[0].message, (
        "metal, live: two full duration lists with no location left the "
        "model editing the wrong bar sixteen sweeps running — the first "
        "divergent note is arithmetic, so it is named"
    )
    assert "should last 1/4 of a whole note, not 1/2" in feedback[0].message


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
    # Eb (75) is not in C; the soprano's first note is prescribed by its
    # entry, and the leap to G that follows resolves nothing — a stepwise
    # continuation would read as a suspension and rightly pass. The bass
    # stays on chord tones so the only clash is the prescribed one.
    voices = _voices(soprano=[75, 79, 76, 77], bass=[48, 52, 55, 48])
    motifs = {"upper_subject": _voices(m=[75, 79, 76, 77])["m"]}

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


def test_a_candidate_is_judged_against_fixed_siblings_at_the_voice_layer() -> None:
    """Sequential counterpoint accepts voices one at a time, so a candidate's
    violations against the finished lines are its own to fix — routed to it,
    at the layer where the repair is one voice wide. Live, a duplicated line
    that reached the section sweep instead arrived as 177 violations."""
    from cadenzra.verification.section import validate_voice_in_context

    voices = _voices(soprano=[72, 74], bass=[60, 62])  # parallel octaves

    feedback = validate_voice_in_context(
        "soprano", voices["soprano"], {"bass": voices["bass"]},
        _section(), None, _style(),
    )

    (item,) = feedback
    assert item.kind == "parallels"
    assert item.voice_id == "soprano", "the finished bass cannot move"
    assert item.routing == "only-free-voice"


def test_a_candidate_with_no_siblings_is_still_judged_against_the_harmony() -> None:
    """The first entry of a sequential section has nothing to collide with,
    but its held tones against the skeleton are already decidable — and a
    held clash caught here costs one voice attempt, not a section sweep."""
    from cadenzra.verification.section import validate_voice_in_context

    voices = _voices(soprano=[71, 71, 71, 71])  # B held across C major

    feedback = validate_voice_in_context(
        "soprano", voices["soprano"], {},
        _section(), _skeleton("C", "C", "C", "C"), _style(),
    )

    assert feedback, "a sustained non-chord tone must be flagged"
    assert all(item.kind == "held_tone" for item in feedback)
    assert all(item.voice_id == "soprano" for item in feedback)


def test_a_collision_only_the_fixed_sibling_could_fix_is_left_to_the_sweep() -> None:
    """Round 9, live: violin2's prescribed entry sat in unison with violin1's
    already-accepted free line, and the voice-layer check ordered violin2 to
    move notes it is forbidden to move — six attempts, verbatim. When the
    router says the free side of the pair is the sibling, the candidate
    cannot fix it and must not be held hostage; the section sweep, which can
    reopen the sibling, owns it."""
    from cadenzra.verification.section import validate_voice_in_context

    voices = _voices(soprano=[72, 74], bass=[60, 62])  # octaves throughout
    section = _section(
        material=[
            MaterialEntry(
                motif_id="m", voice_id="soprano", bar=1, relation="exact"
            )
        ]
    )

    feedback = validate_voice_in_context(
        "soprano",
        voices["soprano"],
        {"bass": voices["bass"]},
        section,
        None,
        _style(),
        motif_notes={"m": voices["soprano"]},  # spans soprano's whole line
    )

    assert feedback == [], (
        "soprano's colliding bars are prescribed and bass is free: only "
        "bass can move, and it is already accepted"
    )


def test_a_held_black_key_is_warned_against_enharmonic_respelling() -> None:
    """Orchestra, live: told 'a step to F4 or G4 lands on the chord', the
    model patched its held F#4 to ges' — the same sounding note — sixteen
    byte-identical sweeps running. The check hears MIDI, and the message
    must say the respelling is not a resolution."""
    voices = _voices(soprano=[66, 66, 66, 66])  # F#4 held across Eb major

    feedback = validate_section(
        voices, _section(key="c minor"), _skeleton("Eb", "Eb", "Eb", "Eb"), _style()
    )

    held = [item for item in feedback if item.kind == "held_tone"]
    assert held, "a sustained non-chord tone must be flagged"
    assert "same sounding note" in held[0].message, (
        "fis and ges must be named as one pitch, or the model respells forever"
    )


def _voice_of(pairs: list[tuple[int, int]]) -> dict[VoiceId, list[NoteEvent]]:
    """One voice from (midi_pitch, quarters) pairs."""
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:soprano"
    midi.tracks.append(track)
    for pitch, quarters in pairs:
        track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
        track.append(
            mido.Message("note_off", channel=0, note=pitch, velocity=0, time=TICKS * quarters)
        )
    return extract_voice_notes(midi)


def test_a_held_tone_that_resolves_by_step_is_a_suspension_not_a_fault() -> None:
    """Orchestra, live: told 'resolve it by step', the model held its F for
    half the bar and stepped to E — the message's own prescription — and the
    check flagged the F again, three identical sweeps. A held clash whose
    next note steps onto the chord is what the message asked for; the check
    must accept what it teaches."""
    resolved = _voice_of([(71, 2), (72, 2)])  # B held, resolving up to C

    feedback = validate_section(
        resolved, _section(), _skeleton("C", "C", "C", "C"), _style()
    )
    assert [i for i in feedback if i.kind == "held_tone"] == [], (
        "hold-then-step-to-chord-tone is a resolved suspension"
    )

    unresolved = _voice_of([(71, 2), (67, 2)])  # B held, leaping away
    feedback = validate_section(
        unresolved, _section(), _skeleton("C", "C", "C", "C"), _style()
    )
    assert [i for i in feedback if i.kind == "held_tone"], (
        "a leap away explains nothing; the clash stays flagged"
    )


def test_a_rhythm_mismatch_is_located_at_the_divergence_not_the_entry_start() -> None:
    """Tool-choir, live: an entry's rhythm diverged in its open final bar,
    but the item pointed at the entry's start — a complete prescribed bar
    the patch permission model rightly protects — so the repair was offered
    the one bar it may not touch and froze for three sweeps. The item's
    location must be the divergence, which is the bar that may change."""
    pitches = [60, 62, 64, 65, 67, 65, 64, 62]
    two_bar_subject = _voices(m=pitches)["m"]
    midi = mido.MidiFile(ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    track.name = "staff:soprano"
    midi.tracks.append(track)
    for index, pitch in enumerate(pitches):
        ticks = TICKS if index < 5 else TICKS // 2  # bar 2 rushes to eighths
        track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
        track.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=ticks))
    diverged = extract_voice_notes(midi)["soprano"]
    section = _section(
        bars=2,
        material=[
            MaterialEntry(motif_id="m", voice_id="soprano", bar=1, relation="exact")
        ],
    )

    feedback = validate_section(
        {"soprano": list(diverged)}, section, NO_HARMONY, _style("allow"),
        {"m": two_bar_subject},
    )

    (item,) = [i for i in feedback if "not its rhythm" in i.message]
    assert "bar 2" in item.message
    assert item.location == Fraction(5, 4), (
        "the divergence (note 6, bar 2 beat 2) is where a repair may act"
    )


def test_a_note_ending_exactly_at_an_entry_boundary_is_free_music() -> None:
    """Double-fugue, live: a held D ending exactly where the cello's bar-13
    entry begins was marked 'prescribed', routed unfixable, sent to a regrid
    that had nothing to fix, and killed the run on the second pass. Notes
    and spans are half-open intervals: touching at the boundary is not
    overlap."""
    section = _section(
        bars=2,
        material=[
            MaterialEntry(motif_id="m", voice_id="soprano", bar=2, relation="exact")
        ],
    )
    # B held through bar 1 (ends exactly at bar 2), then the entry's notes.
    voice = _voice_of([(71, 4), (60, 1), (62, 1), (64, 1), (65, 1)])
    motif = _voices(m=[60, 62, 64, 65])["m"]

    feedback = validate_section(
        voice, section, _skeleton(*["C"] * 8), _style("allow"), {"m": motif}
    )

    held = [item for item in feedback if item.kind == "held_tone"]
    assert held, "the clash is real"
    assert held[0].voice_id == "soprano", "bar 1 is free music: the voice fixes it"
    assert held[0].routing != "unfixable"
