%% A hand-written SATB score in 7/8 (2+2+3) with one additive-meter bar.
%%
%% This is the M0 reference artifact: it exercises the odd-meter requirement,
%% the additive-meter requirement, choral layout with lyrics, and the
%% one-voice-one-MIDI-channel invariant every later analysis keys on.
%%
%% Two syntax notes, both confirmed against the real 2.26 compiler:
%%   * `\time #'(2 2 3) 7/8` carries the beat grouping directly. LilyPond 2.26
%%     no longer needs the separate `\set Timing.beatStructure`.
%%   * `\timeAbbrev` is what 2.26 calls the additive meter; `\compoundMeter`
%%     was renamed and no longer exists.
\version "2.26.0"

sopranoMusic = \absolute {
  \time #'(2 2 3) 7/8
  d''8 d'' e'' e'' f''4. |
  e''8 e'' d'' d'' c''4. |
  \time 3/4
  d''4 e''4 f''4 |
  \timeAbbrev #'((3 4) (1 8))
  e''8 e'' d'' d'' c''4. |
}

altoMusic = \absolute {
  \time #'(2 2 3) 7/8
  a'8 a' a' a' a'4. |
  g'8 g' a' a' a'4. |
  \time 3/4
  a'4 a'4 a'4 |
  \timeAbbrev #'((3 4) (1 8))
  g'8 g' a' a' a'4. |
}

tenorMusic = \absolute {
  \time #'(2 2 3) 7/8
  f'8 f' g' g' a'4. |
  g'8 g' f' f' e'4. |
  \time 3/4
  f'4 g'4 a'4 |
  \timeAbbrev #'((3 4) (1 8))
  g'8 g' f' f' e'4. |
}

bassMusic = \absolute {
  \time #'(2 2 3) 7/8
  d8 d d d d4. |
  c8 c c c c4. |
  \time 3/4
  d4 d4 d4 |
  \timeAbbrev #'((3 4) (1 8))
  c8 c c c c4. |
}

verseOne = \lyricmode {
  Sing the mea -- sure now,
  hold the qui -- et line,
  turn a -- gain,
  hold the qui -- et line,
}

\score {
  \new ChoirStaff <<
    \new Staff \with {
      instrumentName = "S"
      midiInstrument = "choir aahs"
    } { \clef treble \new Voice = "soprano" \sopranoMusic }
    \new Lyrics \lyricsto "soprano" \verseOne
    \new Staff \with {
      instrumentName = "A"
      midiInstrument = "choir aahs"
    } { \clef treble \new Voice = "alto" \altoMusic }
    \new Staff \with {
      instrumentName = "T"
      midiInstrument = "choir aahs"
    } { \clef "treble_8" \new Voice = "tenor" \tenorMusic }
    \new Staff \with {
      instrumentName = "B"
      midiInstrument = "choir aahs"
    } { \clef bass \new Voice = "bass" \bassMusic }
  >>
  \layout {}
  \midi {
    \context {
      \Score
      midiChannelMapping = #'staff
    }
    \tempo 4 = 96
  }
}
