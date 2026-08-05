"""Reading score MIDI back as notes — the one analysis path in the system.

Cadenzra never parses LilyPond notation itself. Pitch-and-timing analysis works
on the score MIDI the compiler produced, which makes the compiler the authority
on what the notation actually says (docs/05).

Two rules from docs/05 shape this module. Analysis reads the **score** domain
only — quantized truth, never the interpreted performance, because verifying a
composition against a deliberate groove would turn every swung eighth into a
rhythm error. And comparisons carry a **tick tolerance**, because deeply nested
tuplets round at tick resolution and a correct-but-rounded rhythm must not
false-positive.
"""

from fractions import Fraction
from typing import Final

import mido
from pydantic import BaseModel

from cadenzra.model.primitives.ids import VoiceId

# A mido "beat" is a quarter note; offsets here are in whole notes.
_WHOLE_NOTES_PER_BEAT: Final = Fraction(1, 4)

# Half a 64th note. Wide enough for nested-tuplet rounding, far narrower than
# any duration a human would notate.
TICK_TOLERANCE: Final = Fraction(1, 128)


class NoteEvent(BaseModel, frozen=True):
    """One sounding note, positioned in whole notes from the file start."""

    midi_pitch: int
    onset: Fraction
    duration: Fraction
    velocity: int
    channel: int
    # Quarter-tones arrive as a pitch bend beside the note (docs/03). Nothing
    # in v1 composes with them; the field exists so analysis never silently
    # reports a quarter-sharp as its natural.
    bend: int | None = None

    @property
    def end(self) -> Fraction:
        return self.onset + self.duration


class VoiceTrack(BaseModel, frozen=True):
    """One voice's notes, as recovered from its own MIDI track.

    `voice_id` comes from the track name LilyPond writes (`<staff>:<voice>`),
    which is the reliable key — channel numbers are distinct but not
    contiguous, so their order means nothing (docs/03).
    """

    voice_id: VoiceId
    channel: int
    notes: list[NoteEvent]


def within_tolerance(left: Fraction, right: Fraction) -> bool:
    """Whether two positions or durations are the same note-value."""
    return abs(left - right) <= TICK_TOLERANCE


def voice_id_of_track(track_name: str) -> str:
    """The voice id inside a LilyPond track name like `soprano:soprano`."""
    return track_name.split(":")[-1]


def extract_voice_tracks(midi: mido.MidiFile) -> list[VoiceTrack]:
    """Every note-carrying track, in file order.

    Raises if a track's notes span more than one channel: that is the
    one-voice-one-channel invariant broken at its source, and everything
    downstream — per-voice dynamics, offsets, bends — silently misbehaves if it
    is allowed through (docs/08, principle 4).
    """
    tracks = []
    for index, track in enumerate(midi.tracks):
        notes = _notes_of(track, midi.ticks_per_beat)
        if not notes:
            continue
        channels = {note.channel for note in notes}
        if len(channels) != 1:
            raise ValueError(
                f"track {index} ({track.name!r}) spans MIDI channels {sorted(channels)}; "
                "one voice must be one track on one channel"
            )
        tracks.append(
            VoiceTrack(
                voice_id=voice_id_of_track(track.name) or str(index),
                channel=channels.pop(),
                notes=notes,
            )
        )
    return tracks


def extract_voice_notes(midi: mido.MidiFile) -> dict[VoiceId, list[NoteEvent]]:
    """Notes keyed by voice id — the form validators work in."""
    return {track.voice_id: track.notes for track in extract_voice_tracks(midi)}


def channel_track_invariant_ok(midi: mido.MidiFile) -> bool:
    """Whether every voice occupies its own track and its own channel."""
    try:
        tracks = extract_voice_tracks(midi)
    except ValueError:
        return False
    channels = [track.channel for track in tracks]
    return len(set(channels)) == len(channels)


def _notes_of(track: mido.MidiTrack, ticks_per_beat: int) -> list[NoteEvent]:
    """Pair note-ons with their note-offs, carrying the active bend along."""
    open_notes: dict[tuple[int, int], tuple[int, int, int | None]] = {}
    bend_by_channel: dict[int, int] = {}
    notes: list[NoteEvent] = []
    tick = 0

    for message in track:
        tick += message.time
        if message.is_meta:
            continue
        if message.type == "pitchwheel":
            bend_by_channel[message.channel] = message.pitch
        elif message.type == "note_on" and message.velocity > 0:
            bend = bend_by_channel.get(message.channel) or None
            open_notes[(message.channel, message.note)] = (tick, message.velocity, bend)
        elif message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        ):
            started = open_notes.pop((message.channel, message.note), None)
            if started is None:
                continue
            onset_tick, velocity, bend = started
            notes.append(
                NoteEvent(
                    midi_pitch=message.note,
                    onset=_whole_notes(onset_tick, ticks_per_beat),
                    duration=_whole_notes(tick - onset_tick, ticks_per_beat),
                    velocity=velocity,
                    channel=message.channel,
                    bend=bend,
                )
            )

    notes.sort(key=lambda note: (note.onset, note.midi_pitch))
    return notes


def _whole_notes(ticks: int, ticks_per_beat: int) -> Fraction:
    return Fraction(ticks, ticks_per_beat) * _WHOLE_NOTES_PER_BEAT


def notes_sounding_at(notes: list[NoteEvent], offset: Fraction) -> list[NoteEvent]:
    """Notes sounding at an instant — the harmonic-alignment checker's view."""
    return [note for note in notes if note.onset <= offset < note.end]


def notes_in_span(
    notes: list[NoteEvent], start: Fraction, end: Fraction
) -> list[NoteEvent]:
    """Notes *starting* inside a half-open span, in order.

    Onsets carry the tolerance so a note landing a tick early still counts as
    beginning the span — which is how a motif entry at bar 5 is located.
    """
    return [
        note for note in notes if start - TICK_TOLERANCE <= note.onset < end - TICK_TOLERANCE
    ]
