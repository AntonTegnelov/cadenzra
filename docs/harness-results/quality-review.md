# Quality review — reading what the system writes

Nine deliberately varied pieces were specified to probe where composition
quality breaks down: restraint, compression, duration, ensemble size,
contrapuntal difficulty, lyric density, and two idioms a long way from the
training gravity of notated art music. Each was to be run end to end, read from
the score and the lyric text (not listened to), and any weakness traced through
the run log to what the model was actually told and thinking.

**Four pieces completed. The API budget ran out partway through.** What follows
separates what was measured from what was not, because a review that blurs the
two is worth nothing.

| Spec | Probes | Status |
|---|---|---|
| `miniature` | can one minute have a shape? | **completed** |
| `minimal` | can it be restrained? | **completed** |
| `tool-choir` | regression against the M6 baseline | **completed** |
| `smoke` | the lyric layer end to end | **completed** |
| `orchestra` | twelve voices, register balance | reached voice generation; budget |
| `dense-lyrics` | six devices at once | reached the motif layer; budget |
| `metal` | idiom outside art music | reached the lyric layer; budget |
| `double-fugue` | two subjects, stretto | reached the second exposition; budget |
| `kpop` | pop form, hook discipline | reached verse 2; budget |
| `longform` | ten minutes, one argument | budget before it started |
| `metal-kpop` | style blending, not matching | budget before it started |

The partial runs are still evidence — a failure at the motif layer says
something even if the piece never finished — and seven faults were found and
fixed from them. But **no claim is made here about long-form coherence,
orchestral balance, double-fugue counterpoint, pop hook writing, or style
fusion.** Those probes were specified and not answered.

---

## What the four completed pieces show

| | target | actual | sections | bars | notes | rejections | dirty compiles |
|---|---:|---:|---:|---:|---:|---:|---:|
| One Minute | 1.00 min | 0.99 | 3 | 16 | 130 | 2 | 0 |
| Slow Machine | 2.00 min | 2.00 | 3 | 40 | 211 | 4 | 0 |
| Vessel | 3.00 min | 2.97 | 5 | 66 | 776 | 2 | 0 |
| Smoke | 0.75 min | 0.77 | 3 | 18 | 113 | 9 | 0 |

**Duration targeting is the strongest single result.** Four pieces, four
different lengths, every one inside 3% of its target — and it is arithmetic the
planner does itself, from bar counts and tempi, before a note exists.

**Zero dirty compiles across 116 compilations.** Every fragment and every
assembled score compiled with no bar-check warnings. The enforcement loop is
doing what it was built for.

### One Minute — the best of the four

A one-minute art song for voice and piano, and a genuine miniature rather than
an excerpt. Three sections, F aeolian → F lydian → F aeolian, 16 bars, 63
seconds of audio.

The vocal line has a real arch. It opens `f'2 g'4. a'8`, reaches `c''` in bar 3,
and the *whole piece* peaks at `f''` — exactly the top of the declared range —
in section B, at the point the section's own intent called "a tender peak".
Section C then inverts A's opening cell (`a'2 f'4. g'8` against `f'2 g'4. a'8`)
and closes on the sustained open fifth the plan asked for. The piano changes
texture underneath, chordal `<f, c g>` voicings in A giving way to broken
figuration in C.

The lyrics scan exactly — 16 syllables against 16 notes — and the devices are
realized rather than labelled:

> Cool pale light / on the emp-ty floor, / motes in flight / by the o-pen door.

Dust in a shaft of light standing in for grief is an objective correlative doing
its job, and light/flight, floor/door hold the declared ABAB. Section B's "warm
light **rings** with soft **golden sound**" is a real synesthesia. Section C
ends four consecutive lines with "in peace" — textbook epistrophe.

**The weakness:** that last line is "and rest in peace", which reads as a death
notice in a song about leaving a house. The device is correct and the phrase is
a cliché, and nothing in the system can tell the difference. That gap is
structural, not a bug — see "what no validator can reach" below.

### Slow Machine — the process is real

Minimalism for two pianos. Section C is the best writing in the set, because the
process is visible in the notation itself:

```
a,4 e4 c4 e4 |  a,4 e4 c4 e4 |  a,4 e4 c4 r4 |  a,4 e4 r2 |
f,4 c4 a4 c4 |  f,4 c4 a4 r4 |  f,4 c4 r2 |  f,4 r2. |  …  a,1 |
```

Notes drop away one per repetition until a single held A — precisely the
"stripping notes until only a single tone" the section's intent declared. The
left hand arpeggiates the A-minor triad under a stepwise right hand, which is
tintinnabuli correctly understood, not just correctly named.

**The weakness:** section A's "process" is sequence-by-transposition
(A→F→C→G→A), a Baroque device wearing minimalist clothes. The style pack
described an additive process and the music delivered a harmonic sequence. The
model knows the vocabulary better than it knows the technique.

**A spec-design lesson, not a system fault:** four of the run's rejections were
range violations caused by my declaring `piano_right` as C4–C6 and `piano_left`
as C2–C4. Real piano writing crosses hands constantly. The validators enforced
the spec correctly; the spec was a poor model of a piano.

### Vessel — better than its M6 baseline

The same commission as M6, re-run with the lyric subsystem in place. 66 bars
against the baseline's 54, five sections across three meters, **two rejections
for the entire run** against the four assembly defects M6 surfaced.

The 7/8 section locks its 2+2+3 grouping across all sixteen bars and is modally
correct, but melodically angular — `ees'' g' d''` is a descending sixth answered
by a rising fifth, repeated as a *shape* rather than developed as a line. The
5/4 section is markedly better: `b'4. cis''8 d''4 cis''2 | fis''4. e''8 d''4
cis''2` breathes, moves by step, and arches up to `a''` at the climax.

The lyrics are coordinated — one language, one story, four voices — which is
what the subsystem was built for. Section C's polyptoton is genuinely
accomplished, four times over:

> The surge that sur-ges, sur-ging in the clay … rings, it rang, a rin-ging
> sound … The strain that strains, now strai-ning all the stone … it swells and
> swelled, a swel-ling

**The weakness:** the harmony is nearly static by design (a D pedal throughout),
which is authentic to the idiom and also means the piece alternates between two
modal colours rather than going anywhere harmonically.

### Smoke — where the device machinery misfired

The smallest piece, and the one that exposed the most. Its lyrics are the worst
of the four, and the run log says exactly why: the planner assigned `ekphrasis`
— describing an artwork — to a piece about mist on a lake. The writer duly
invented a painting that is nowhere in the story:

> Framed in grey lake mist / Framed in pain-ted twist / Can-vas dark / Can-vas,
> cold and stark

And `prosodic_dissonance` + `polyptoton` on a section of held notes produced the
contortion "heat / a-rise / re-heat / to skies", where "re-heat" is a
microwave word doing duty as a polyptoton of "heat".

Both are the same fault: **a device forced where it does not belong drags the
lyric away from its subject.** Fixed at the planner (below).

---

## Faults found, and where each was fixed

Seven, all traced through the run log to a specific prompt, validator or parser.
Every one is a fault only a piece of this kind reaches.

| # | Fault | Found by | Fixed in |
|---|---|---|---|
| 1 | `derive_style` was the only layer with no retry; one mistyped cell meter (`3/3`) ended a twelve-voice run before it wrote a note | orchestra | `app/pipeline.py` |
| 2 | One motif brief carried by three voices came back as three per-voice variants, so the theme the plan named did not exist — and the retry repeated it | dense-lyrics | `llm/prompts/structured.py` |
| 3 | The same layer wrote `b3 4 fis4 8` — scientific pitch with the duration split off, learned from the range display directly above it | dense-lyrics | worked example, built from the meter |
| 4 | `cb` and `gbes`: the note-name rule was taught by two examples and generalized incompletely | orchestra | the rule, stated, in the prompt and both validators |
| 5 | `Bb9sus4` unparseable, losing a section's harmony | orchestra | `notation/chords.py` |
| 6 | A refrain failed on **hyphen spacing alone** — `i--ron` tokenized as one syllable, so identical words compared unequal | metal | `llm/parsers/lyrics.py` |
| 7 | Devices forced into sections that did not suit them; and a text-only reader was asked about `prosodic_dissonance`, which is stress against *beat* and unanswerable without the music | smoke | planner prompt; `TEXT_OBSERVABLE_DEVICES` |

**Fault 6 is the most interesting**, because it is the failure mode this project
keeps re-learning in new clothes: a *surface* difference with no musical meaning
was allowed to become a correctness failure. The writer typed `i--ron` where the
source had `i -- ron`. Both mean the same thing to a musician and only one is a
hyphen to LilyPond. The refrain check compared word sequences, the hyphen
spacing changed the tokenization, and a section spent its entire budget failing
a comparison that could never have succeeded. The rule this reinforces is
docs/03's: **the surface may be forgiving; the system stays strict underneath.**

**Fault 1 is the most costly per unit of code.** One layer without a retry loop
turned a single typo'd character into a dead run of twelve voices. Every other
layer had the loop already.

Two operational notes, not system faults: running eight pieces concurrently
exhausted the API rate limit, and the client's three immediate retries burned
the budget in about a second. Backoff now separates "not yet" (wait) from a spent
spending cap (do not — waiting cannot fix a budget).

---

## What no validator can reach

Reading four scores makes the boundary concrete.

**What the system guarantees, and delivers:** every bar fills its meter, every
note is in range, durations are exact, the form adds up to the requested
duration, declared motif entries are what they claim, syllables fit their notes,
declared rhyme schemes hold, refrains reuse their words, and every artifact
descends from one text file.

**What it cannot judge, and does not pretend to:** whether `ees'' g' d''`
repeated eight times is a line or a shape. Whether "rest in peace" is the wrong
register for a song about a house. Whether a harmonic sequence counts as an
additive process. Whether a static pedal is hypnotic or inert.

These are exactly the judgments docs/01 assigns to a human, and reading the
scores confirms the split is drawn in the right place. Every failure the system
*can* catch, it caught; every weakness above needed a reader.

One thing the review does suggest is worth measuring later: the model is
consistently better at *naming* a technique than at *executing* it — tintinnabuli
correct, additive process not; polyptoton excellent, ekphrasis invented. That is
a harness question (does showing a worked example of a technique raise the rate
at which it is realized?) rather than a validator question, and it is not
answered here.

## Reproducing

```bash
uv run cadenzra compose miniature
```

Any of the thirteen specs in `app/specs.py`. Each run writes its log to
`out/<spec>/runs/<timestamp>/` — `llm.jsonl` for verbatim prompts and responses,
`narrative.md` for the same flow with the model's reasoning, `technical.log` at
whatever `--log-level` asks for. Every diagnosis above came from reading those.
