"""The M0 gate: the rendering boundary, against the real binaries.

These are the version-drift tripwire (docs/09). Three of them also pin the
empirical answers M0 exists to establish, and the design leans on all three:

  (a) one voice = one MIDI track = one MIDI channel, which every analysis
      validator and every per-channel performance mechanism depends on;
  (b) quarter-tone accidentals reach MIDI as pitch bends, which is how the
      microtonal door stays open;
  (c) the SoundFont honors CC11, without which the score/performance split
      could not make a crescendo audible at all.

(c) is pulled forward from the performance milestone on purpose: a SoundFont
that ignored expression would invalidate a design commitment, and finding that
out at M4 would be finding it out late.
"""

import math
import wave
from array import array
from pathlib import Path

import mido
import pytest

from cadenzra.common.errors import LilypondCompileError
from cadenzra.model.artifacts import CompileResult
from cadenzra.rendering.fluidsynth import DEFAULT_SOUNDFONT, FluidsynthAdapter
from cadenzra.rendering.lilypond import LilypondAdapter

pytestmark = pytest.mark.integration

LILY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "lily"


@pytest.fixture(scope="module")
def renderer() -> LilypondAdapter:
    return LilypondAdapter()


@pytest.fixture(scope="module")
def synthesizer() -> FluidsynthAdapter:
    return FluidsynthAdapter()


def _compile(renderer: LilypondAdapter, name: str, workdir: Path) -> CompileResult:
    source = (LILY_FIXTURES / f"{name}.ly").read_text(encoding="utf-8")
    return renderer.compile(source, workdir)


def _voice_tracks(midi: mido.MidiFile) -> dict[str, list[mido.Message]]:
    """Tracks that carry notes, keyed by the voice name LilyPond wrote.

    LilyPond names the track after the `\\new Voice = "..."` context, prefixed
    with the staff name and a colon.
    """
    tracks = {}
    for track in midi.tracks:
        notes = [m for m in track if m.type in ("note_on", "note_off")]
        if notes:
            tracks[track.name.split(":")[-1]] = notes
    return tracks


def test_the_toolchain_is_the_version_we_parse(renderer: LilypondAdapter) -> None:
    assert renderer.assert_version() == "2.26"


def test_a_valid_satb_score_compiles_to_pdf_and_score_midi(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    result = _compile(renderer, "satb_7_8_valid", tmp_path)

    assert result.clean
    assert result.pdf_path is not None and result.pdf_path.stat().st_size > 0
    assert result.midi_path is not None and result.midi_path.stat().st_size > 0


def test_odd_and_additive_meters_survive_compilation(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """The fixture holds 7/8 (2+2+3), 3/4, and an additive 3/4+1/8 bar. A
    meter LilyPond mis-measured would surface as a bar-check warning."""
    result = _compile(renderer, "satb_7_8_valid", tmp_path)

    assert result.bar_check_warnings == []


def test_an_overfilled_bar_is_reported_as_a_located_warning(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    result = _compile(renderer, "satb_7_8_broken", tmp_path)

    assert result.ok, "a bar check failure is a warning; LilyPond still exits zero"
    assert not result.clean
    assert len(result.bar_check_warnings) == 1
    assert result.bar_check_warnings[0].line == 17


def test_a_syntax_error_raises_with_the_compiler_output_attached(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    with pytest.raises(LilypondCompileError) as caught:
        renderer.compile('\\version "2.26.0"\n\\score { \\new Staff { c4 \n', tmp_path)

    assert "error" in caught.value.output


def test_one_voice_is_one_track_on_one_channel(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """Empirical check (a). The assembler's hard invariant (docs/03): the
    analysis validators key on it, and every per-channel performance mechanism
    — CC dynamics, timing offsets, pitch bend — exists only because of it."""
    result = _compile(renderer, "satb_7_8_valid", tmp_path)
    assert result.midi_path is not None
    midi = mido.MidiFile(result.midi_path)

    tracks = _voice_tracks(midi)
    assert set(tracks) == {"soprano", "alto", "tenor", "bass"}

    channels = {}
    for voice, notes in tracks.items():
        voice_channels = {message.channel for message in notes}
        assert len(voice_channels) == 1, f"{voice} spans channels {voice_channels}"
        channels[voice] = voice_channels.pop()

    assert len(set(channels.values())) == 4, f"voices share channels: {channels}"


def test_voice_channels_are_distinct_but_not_contiguous(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """A consequence of (a) worth pinning: a Lyrics context consumes a channel
    number, so channels are 0, 2, 3, 4 for SATB. Analysis must read each
    track's own channel and never assume 0..n-1."""
    result = _compile(renderer, "satb_7_8_valid", tmp_path)
    assert result.midi_path is not None

    channels = sorted(
        {message.channel for notes in _voice_tracks(mido.MidiFile(result.midi_path)).values()
         for message in notes}
    )

    assert channels == [0, 2, 3, 4]


def test_quarter_tones_reach_midi_as_pitch_bends(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """Empirical check (b). A quarter-tone is half a semitone; against the
    default +/-2-semitone bend range that is 8192/4 = 2048."""
    result = _compile(renderer, "quartertone", tmp_path)
    assert result.midi_path is not None

    bends = [
        message.pitch
        for track in mido.MidiFile(result.midi_path).tracks
        for message in track
        if message.type == "pitchwheel"
    ]

    assert 2048 in bends, "quarter-sharp did not produce an upward bend"
    assert -2048 in bends, "quarter-flat did not produce a downward bend"


def test_audio_renders_from_score_midi(
    renderer: LilypondAdapter, synthesizer: FluidsynthAdapter, tmp_path: Path
) -> None:
    result = _compile(renderer, "satb_7_8_valid", tmp_path)
    assert result.midi_path is not None

    audio = synthesizer.render(result.midi_path, [], tmp_path / "audio.wav")

    with wave.open(str(audio)) as handle:
        seconds = handle.getnframes() / handle.getframerate()
    expected = mido.MidiFile(result.midi_path).length
    assert expected * 0.8 <= seconds <= expected * 1.5 + 3


def _rms(path: Path, start_s: float, end_s: float) -> float:
    with wave.open(str(path)) as handle:
        rate, channels = handle.getframerate(), handle.getnchannels()
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    mono = samples[0::channels][int(rate * start_s) : int(rate * end_s)]
    if not mono:
        return 0.0
    return math.sqrt(sum(float(s) * s for s in mono) / len(mono))


def _held_note_at_expression(level: int, path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=384)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=0))
    track.append(mido.Message("program_change", channel=0, program=52, time=0))
    track.append(mido.Message("control_change", channel=0, control=11, value=level, time=0))
    track.append(mido.Message("note_on", channel=0, note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=384 * 3))
    midi.save(path)


def test_the_soundfont_actually_responds_to_expression(
    synthesizer: FluidsynthAdapter, tmp_path: Path
) -> None:
    """Empirical check (c). The first piece's held-chord crescendos are
    inaudible unless CC11 moves amplitude, so this is a design precondition,
    not a nicety — and a SoundFont that ignored it would fail silently."""
    quiet_midi, loud_midi = tmp_path / "quiet.mid", tmp_path / "loud.mid"
    _held_note_at_expression(20, quiet_midi)
    _held_note_at_expression(127, loud_midi)

    quiet = _rms(synthesizer.render(quiet_midi, [], tmp_path / "quiet.wav"), 0.5, 2.0)
    loud = _rms(synthesizer.render(loud_midi, [], tmp_path / "loud.wav"), 0.5, 2.0)

    assert loud > quiet * 3, f"CC11 barely moved amplitude: {quiet:.1f} -> {loud:.1f}"


def test_the_default_soundfont_is_where_the_config_expects_it() -> None:
    assert DEFAULT_SOUNDFONT.exists()
