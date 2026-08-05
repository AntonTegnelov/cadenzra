%% The valid SATB fixture with one bar deliberately overfilled.
%%
%% The alto's second bar carries eight eighth-notes in 7/8. LilyPond still
%% exits zero — a bar check failure is a *warning* — which is exactly why
%% `CompileResult.ok` is not enough for a validator and `clean` exists.
\version "2.26.0"

sopranoMusic = \absolute {
  \time #'(2 2 3) 7/8
  d''8 d'' e'' e'' f''4. |
  e''8 e'' d'' d'' c''4. |
}

altoMusic = \absolute {
  \time #'(2 2 3) 7/8
  a'8 a' a' a' a'4. |
  g'8 g' a' a' a' a' a' a' |
}

tenorMusic = \absolute {
  \time #'(2 2 3) 7/8
  f'8 f' g' g' a'4. |
  g'8 g' f' f' e'4. |
}

bassMusic = \absolute {
  \time #'(2 2 3) 7/8
  d8 d d d d4. |
  c8 c c c c4. |
}

\score {
  \new ChoirStaff <<
    \new Staff \with { midiInstrument = "choir aahs" } {
      \clef treble \new Voice = "soprano" \sopranoMusic
    }
    \new Staff \with { midiInstrument = "choir aahs" } {
      \clef treble \new Voice = "alto" \altoMusic
    }
    \new Staff \with { midiInstrument = "choir aahs" } {
      \clef "treble_8" \new Voice = "tenor" \tenorMusic
    }
    \new Staff \with { midiInstrument = "choir aahs" } {
      \clef bass \new Voice = "bass" \bassMusic
    }
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
