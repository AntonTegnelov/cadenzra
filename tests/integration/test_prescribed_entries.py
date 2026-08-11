"""A prescribed entry survives every downstream check verbatim.

This is the double-fugue trap (F1) driven through the real pipeline: a
subject written below the entering voice's floor, whose transposed-entry
instruction had no legal answer at the written octave — 30 identical live
failures. The fix computes the finished bars (relation applied, register
lifted by whole octaves, rebarred into the section's meter) from the *compiled*
motif, so these tests run real LilyPond end-to-end: motif analysis →
`_materials_for` → a token-for-token copy through `validate_voice` and the
entry checks. If any link is off — MIDI durations not exact, spelling wrong,
ties misplaced — the prescription either never fires or fails its own checks,
and this file is where that shows up.
"""

from pathlib import Path

import mido
import pytest

from cadenzra.app.compose import _materials_for
from cadenzra.app.pipeline import analyzed_motifs
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import MeterSpec, simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState
from cadenzra.model.structure import (
    DynamicsPlan,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.rendering.lilypond import LilypondAdapter
from cadenzra.verification.midi_analysis import NoteEvent, extract_voice_notes
from cadenzra.verification.transposition import (
    intervals_match_under_relation,
    parse_relation,
    rhythm_profile_matches,
)
from cadenzra.verification.voice import validate_voice

pytestmark = pytest.mark.integration

FOUR_FOUR = simple_meter(4, 4)
FIVE_FOUR = simple_meter(5, 4)

VIOLIN2 = VoiceSpec(
    voice_id="violin2",
    kind="instrument",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=6),
    midi_program=41,
)


@pytest.fixture(scope="module")
def renderer() -> LilypondAdapter:
    return LilypondAdapter()


def _section(
    section_id: str,
    meter: MeterSpec,
    bars: int,
    key: str,
    *entries: MaterialEntry,
) -> SectionPlan:
    return SectionPlan(
        section_id=section_id,
        bars=bars,
        meter=meter,
        key=key,
        tempo_bpm=96,
        texture="imitative",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["violin2"],
        material=list(entries),
    )


def _state(library: MotifLibrary, plan: StructurePlan) -> PipelineState:
    spec = PieceSpec(
        title="Prescription",
        style_prompt="s",
        voices=[VIOLIN2],
        meters_allowed=[FOUR_FOUR, FIVE_FOUR],
        target_minutes=4 / 90,
    )
    return PipelineState(spec=spec, style=StylePack(), structure=plan, motifs=library)


def _compiled_notes(
    music: str,
    meter: MeterSpec,
    renderer: LilypondAdapter,
    workdir: Path,
) -> list[NoteEvent]:
    result = renderer.compile(scaffold_fragment(music, meter).source, workdir)
    assert result.midi_path is not None
    notes = next(iter(extract_voice_notes(mido.MidiFile(result.midi_path)).values()))
    return sorted(notes, key=lambda note: note.onset)


def test_the_double_fugue_shape_passes_every_check_verbatim(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """The subject is written G2–C3; 'P5 up' lands on D3, below the violin's
    G3 floor — the closed instruction with no legal answer. The prescription
    lifts the realized entry a whole octave and hands over finished bars; a
    token-for-token copy must pass range, meter, and both entry checks."""
    library = MotifLibrary(
        motifs={
            "subject": Motif(
                motif_id="subject", role="subject", lily_music="g,4 a,4 b,4 c4 |"
            )
        }
    )
    entry = MaterialEntry(
        motif_id="subject", voice_id="violin2", bar=1, relation="P5 up"
    )
    section = _section("A", FOUR_FOUR, 1, "g major", entry)
    state = _state(library, StructurePlan(sections=[section]))

    motif_events = analyzed_motifs(state, renderer, tmp_path / "motifs")
    (instruction,) = _materials_for(state, section, "violin2", motif_events)

    assert instruction.prescribed_lily == "d'4 e'4 fis'4 g'4 |"
    assert instruction.prescribed_bars == (1,)
    assert instruction.max_adjustable == 0

    part = VoicePart(
        section_id="A", voice_id="violin2", lily_music=instruction.prescribed_lily
    )
    assert validate_voice(part, VIOLIN2, section, renderer, tmp_path / "voice") == []

    subject = motif_events["subject"]
    candidate = _compiled_notes(
        instruction.prescribed_lily, FOUR_FOUR, renderer, tmp_path / "entry"
    )[: len(subject)]
    result = intervals_match_under_relation(
        subject, candidate, parse_relation("P5 up")
    )
    assert result.ok, result.detail
    assert rhythm_profile_matches(subject, candidate)


def test_a_four_four_theme_is_rebarred_into_a_five_four_section(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """The longform trap (F2): a theme shown with its home barlines invites
    the model to reproduce a 4/4 bar inside 5/4. The prescription arrives
    already rebarred — barlines where the section's meter puts them, the
    crossing half note split into tied quarters — and a copy that completes
    the open final bar passes the meter and entry checks."""
    library = MotifLibrary(
        motifs={
            "theme": Motif(
                motif_id="theme",
                role="theme",
                lily_music="c'4 d'4 e'4 f'4 | g'2 a'2 |",
            )
        }
    )
    home = _section(
        "A",
        FOUR_FOUR,
        2,
        "c major",
        MaterialEntry(motif_id="theme", voice_id="violin2", bar=1, relation="exact"),
    )
    foreign = _section(
        "B",
        FIVE_FOUR,
        2,
        "c major",
        MaterialEntry(motif_id="theme", voice_id="violin2", bar=1, relation="exact"),
    )
    state = _state(library, StructurePlan(sections=[home, foreign]))

    motif_events = analyzed_motifs(state, renderer, tmp_path / "motifs")
    (instruction,) = _materials_for(state, foreign, "violin2", motif_events)

    assert instruction.prescribed_lily == "c'4 d'4 e'4 f'4 g'4~ | g'4 a'2"
    assert instruction.prescribed_bars == (1, 2)

    completed = instruction.prescribed_lily + " b'4 c''4 |"
    part = VoicePart(section_id="B", voice_id="violin2", lily_music=completed)
    assert validate_voice(part, VIOLIN2, foreign, renderer, tmp_path / "voice") == []

    subject = motif_events["theme"]
    candidate = _compiled_notes(completed, FIVE_FOUR, renderer, tmp_path / "entry")[
        : len(subject)
    ]
    result = intervals_match_under_relation(
        subject, candidate, parse_relation("exact")
    )
    assert result.ok, result.detail
    assert rhythm_profile_matches(subject, candidate), (
        "the tied split must be heard as the original half note"
    )
