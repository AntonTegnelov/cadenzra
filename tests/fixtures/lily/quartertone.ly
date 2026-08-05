%% Quarter-tone accidentals, for the M0 empirical check.
%%
%% The question this answers: does LilyPond's MIDI backend realize quarter-
%% tones as pitch bends? The answer decides how the microtonal door stays
%% open (docs/03) and is recorded there.
\version "2.26.0"

\score {
  \new Staff \absolute {
    \time 4/4
    c'4 cih'4 d'4 deh'4 |
  }
  \layout {}
  \midi { \tempo 4 = 60 }
}
