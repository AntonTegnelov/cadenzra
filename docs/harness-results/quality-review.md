# Quality review — reading what the system writes

Nine deliberately varied pieces were specified to probe where composition
quality breaks down: restraint, compression, duration, ensemble size,
contrapuntal difficulty, lyric density, and two idioms a long way from the
training gravity of notated art music. Each was run end to end and read from the
score and the lyric text — not listened to — and every weakness was traced
through the run log to what the model was actually told and thinking.

**Six pieces completed. Three did not, and their failures are the most
informative results here.** Thirteen faults were found and fixed along the way,
each diagnosed from a log rather than guessed at.

| Spec | Probes | Result |
|---|---|---|
| `miniature` | can one minute have a shape? | **completed** |
| `minimal` | can it be restrained? | **completed** |
| `tool-choir` | regression against the M6 baseline | **completed** |
| `metal` | idiom far outside art music | **completed** |
| `dense-lyrics` | six devices at once | **completed** |
| `smoke` | the lyric layer end to end | **completed** |
| `longform` | ten minutes, one argument | 194 bars, 25 parts, then a motif entry |
| `double-fugue` | two subjects, stretto | the counterpoint plateau, below |
| `orchestra` | twelve voices, register balance | 48 parts, then one last clash — see below |

---

## The numbers

| | target | actual | sections | bars | notes | rejections | dirty compiles |
|---|---:|---:|---:|---:|---:|---:|---:|
| One Minute | 1.00 min | 0.99 | 3 | 16 | 130 | 2 | 0 |
| Slow Machine | 2.00 min | 2.00 | 3 | 40 | 211 | 4 | 0 |
| Vessel | 3.00 min | 2.97 | 5 | 66 | 776 | 2 | 0 |
| Iron Liturgy | 2.50 min | 2.33 | 6 | 78 | 2,250 | 6 | 0 |
| Gallery of Salt | 2.50 min | 2.36 | 6 | 62 | 1,491 | 9 | 0 |
| Smoke | 0.75 min | 0.77 | 3 | 18 | 113 | 9 | 0 |

**Duration targeting is the strongest single result.** Six pieces, six lengths
from 45 seconds to three minutes, every one inside 7% and four inside 3% — and
it is arithmetic the planner does itself, from bar counts and tempi, before a
note exists.

**Zero dirty compiles across 194 compilations.** Every fragment and every
assembled score compiled with no bar-check warnings.

---

## The pieces

### One Minute — the best of the set

A one-minute art song, and a genuine miniature rather than an excerpt. F aeolian
→ F lydian → F aeolian in 16 bars, 63 seconds of audio.

The vocal line has a real arch: it opens `f'2 g'4. a'8`, reaches `c''` in bar 3,
and the *whole piece* peaks at `f''` — exactly the top of the declared range —
in section B, at the point the section's own intent called "a tender peak".
Section C inverts A's opening cell (`a'2 f'4. g'8` against `f'2 g'4. a'8`) and
closes on the sustained open fifth the plan asked for.

The lyrics scan exactly, 16 syllables against 16 notes, and the devices are
realized rather than labelled — dust in a shaft of light for grief (objective
correlative), "warm light **rings** with soft **golden sound**" (synesthesia),
four lines closing "in peace" (epistrophe).

**Weakness:** that last line is "and rest in peace", which reads as a death
notice in a song about leaving a house. The device is correct and the phrase is
a cliché, and nothing in the system can tell the difference.

### Iron Liturgy — the strongest idiom fidelity

Riff-driven metal, and it is real metal writing rather than art music in metal
clothes. Guitar 2 alternates power chords with palm-muted single notes —
`<e, b,>8 e,16 e,16 <e, b,>8 e,16 e,16` — moving by half-step and tritone
(`<f, c>`, `<bes, f>`, `<fis, cis>`); the bass doubles an octave below in exact
rhythmic lockstep; the dotted `8. 16` figures give the gallop. The 11/8 section
shifts the tonal centre up a half-step into F Phrygian, which is a genuine
prog-metal move. 2,250 notes, the densest piece by far.

**Weakness, and it drove a fix:** the lyrics came back as four lines per
section regardless of length, so a 12-bar section got 12-syllable lines and a
20-bar one got 32-syllable paragraphs. The cause was ours — see the rhyme-scheme
fix below.

### Slow Machine — the process is real

Section C is the best-made passage in the set, because the process is visible
in the notation itself:

```
a,4 e4 c4 e4 |  a,4 e4 c4 e4 |  a,4 e4 c4 r4 |  a,4 e4 r2 |
f,4 c4 a4 c4 |  f,4 c4 a4 r4 |  f,4 c4 r2 |  f,4 r2. |  …  a,1 |
```

Notes drop away one per repetition until a single held A — exactly the
"stripping notes until only a single tone" its intent declared — with the left
hand arpeggiating the A-minor triad under a stepwise right hand, which is
tintinnabuli correctly understood rather than merely named.

**Weakness:** section A's "process" is sequence-by-transposition (A→F→C→G→A), a
Baroque device wearing minimalist clothes. The style pack described an additive
process; the music delivered a harmonic sequence.

**A spec-design lesson, not a system fault:** four rejections were range
violations caused by declaring `piano_right` C4–C6 and `piano_left` C2–C4. Real
piano writing crosses hands constantly. The validators enforced the spec
correctly; the spec was a poor model of a piano.

### Vessel — better than its M6 baseline

The same commission re-run with the lyric subsystem in place: 66 bars against
54, five sections across three meters, **two rejections for the whole run**
against the four assembly defects M6 surfaced. Section C's polyptoton is
accomplished four times over — "The surge that sur-ges, sur-ging in the clay …
rings, it rang, a rin-ging sound … The strain that strains, now strai-ning".

**Weakness:** the 7/8 section is melodically angular. `ees'' g' d''` is a
descending sixth answered by a rising fifth, repeated as a *shape* rather than
developed as a line. The 5/4 section is markedly better — `b'4. cis''8 d''4
cis''2` breathes and arches to `a''`.

### Gallery of Salt — density is what you get when you ask for density

The maximum-load lyric probe: six devices at once, dense internal rhyme, an
AABB scheme. The result splits sharply, and the split is the finding.

Where a device serves the sense, the writing is good. Section B's polyptoton
runs nine times and reads as poetry:

> the cu-ring brine / cured bone and spine / it traps the breath / trapped fast
> in dark death

Section C's melopoeia works too — "fine silt and grind-ing dust / cold lime and
chalk-y crust / coarse sand and rasp-ing grit" genuinely abrades.

Where the request is for rhyme *density itself*, the constraint eats the
meaning:

> Clear glass, sear grass / Glass mass, years pass … Prime chime, lost time

"Sear grass" in a museum; "prime chime" means nothing. Section D is worse — "in
fright I sight white, / through night shines bright light" is five rhymes in two
lines and no sense left.

**And the one device that needed *description* lost to the ones that needed
sound.** `ekphrasis` was requested for section A — a story explicitly about
looking at objects in vitrines — and never appears. The blind reader, told
nothing about what had been asked for, independently reported finding no sign of
it, which is the same verdict a human reading reaches. That agreement is the
best evidence in this review that the blinded-observation design works.

### The three that did not finish

**Double Fugue** failed loudly after three cross-voice attempts, and the numbers
are the most useful thing in this review: **239 parallel-octave violations, then
48, then 48 again.** An exact plateau is not a hard problem, it is a blind one —
diagnosed and fixed below.

**Ascent** is the clearest evidence that the repair fix works. Re-run after it,
its cross-voice attempts went **9 harmonic clashes → 0 → 1**, with **zero
parallels in all three**, across 48 parts and twelve voices. It failed on a
single remaining clash with a budget of three; one more attempt would very
likely have cleared it. Compare the pre-fix double fugue: 239 → 48 → 48.

Its harmony sits in the Eb-minor/Cb region — `Cb`, `Gb`, `Abm`, `Cb7`, `Ebm/Gb`
— and every surviving complaint is a voice writing a natural or a sharp against
a remote flat-spelled chord. The clashes are real in pitch-class terms, not
spelling artifacts, but the *pattern* is: extreme flat harmony pulls voices
toward enharmonic spellings the chord does not contain. Worth measuring against
a piece in a plainer key before concluding anything.

**The Long Field** reached **194 bars and 25 parts across five movements**
before failing on motif-entry fidelity: the viola's declared P5-up entry departs
from the subject at bar 5, beat 4. Notably it recorded **zero parallels in all
three attempts**, where the pre-fix fugue had 239 — the sibling-context fix
appears to have helped, though a single run is not a measurement.

Reproducing a motif exactly under transposition, 194 bars into a piece, is the
hardest thing asked anywhere in this set, and the system refused to ship a fugue
entry that was not the subject. That is the designed behaviour and the whole
reason the check exists.

---

## The thirteen faults, and where each was fixed

Every one is a fault only a piece of this kind reaches.

| # | Fault | Found by | Fixed in |
|---|---|---|---|
| 1 | `derive_style` was the only layer with no retry; one mistyped cell meter (`3/3`) ended a twelve-voice run before it wrote a note | orchestra | `app/pipeline.py` |
| 2 | One motif brief carried by three voices came back as three per-voice variants, so the theme the plan named did not exist | dense-lyrics | motif prompt |
| 3 | The motif layer wrote `b3 4 fis4 8` — scientific pitch with the duration split off, learned from the range display above it | dense-lyrics | worked example, built from the meter |
| 4 | `cb` and `gbes`: the note-name rule was taught by two examples and generalized incompletely | orchestra | the rule stated, in prompt and validators |
| 5 | `Bb9sus4` unparseable, losing a section's harmony | orchestra | `notation/chords.py` |
| 6 | A refrain failed on **hyphen spacing alone** — `i--ron` tokenized as one syllable | metal | `llm/parsers/lyrics.py` |
| 7 | Devices forced where they did not suit; `prosodic_dissonance` asked of a text-only reader, which is unanswerable without the music | smoke | planner prompt; `TEXT_OBSERVABLE_DEVICES` |
| 8 | A rate limit spent three immediate retries in a second; a spending cap is not worth waiting for at all | all | client backoff |
| 9 | A four-letter rhyme scheme demanded exactly four lines, so a 20-bar section got 32-syllable paragraphs | metal | schemes are stanzas that repeat |
| 10 | Cross-voice repairs ran against a stale snapshot, so each voice avoided the others' *old* music | double-fugue | repairs accumulate |
| 11 | A voice told "you move in parallel octaves with the viola" was never shown the viola | double-fugue | `VoiceContext.siblings` |
| 12 | A motif an eighth short of 4/4 was told only that "its bars do not fill the meter" — the compiler had said 1/8 | metal-kpop | quote the remainder |
| 13 | A refrain had to be *exactly* equal, rejecting a final chorus that extended the hook, a chorus that doubled it onto another voice, and one with less music than its source | kpop, metal, metal-kpop | agreement over the shorter span |

**Faults 10 and 11 are the same mistake the lyrics bug was**, in the counterpoint
domain: *generation that must coordinate cannot run against a stale snapshot, and
cannot fix a relationship it is not shown.* Finding it twice, in two unrelated
layers, is the strongest architectural signal in this exercise.

**Fault 13 took three pieces to see properly.** Each rejection looked like a
model failure and was ours: the contract said "identical" where music means
"the words come back". Reading each failure alone produced a wrong fix twice
before the symmetric statement — the shorter of the two is a contiguous run of
the longer — covered every case.

**Fault 6 is the failure mode this project keeps re-learning in new clothes:** a
*surface* difference with no musical meaning became a correctness failure. Both
`i--ron` and `i -- ron` mean the same thing to a musician; only one is a hyphen
to LilyPond.

**Faults 4 and 12 both violated a rule CLAUDE.md states outright** — never guess
a diagnosis when the real one is available. In one case a rule was taught by
example instead of stated; in the other, a validator paraphrased a compiler
message that named the exact remainder. Each cost a full run.

---

## What no validator can reach

Reading six scores makes the boundary concrete.

**What the system guarantees, and delivers:** every bar fills its meter, every
note is in range, durations are exact, the form adds up to the requested
duration, declared motif entries are what they claim, syllables fit their notes,
declared rhyme schemes hold, refrains reuse their words, and every artifact
descends from one text file.

**What it cannot judge, and does not pretend to:** whether `ees'' g' d''`
repeated eight times is a line or a shape. Whether "rest in peace" is the wrong
register for a song about a house. Whether "prime chime" means anything. Whether
a harmonic sequence counts as an additive process.

Every failure the system *can* catch, it caught. Every weakness above needed a
reader.

## What is still open

**Chrome Teeth**, the metal/K-pop fusion, never got past its motif layer. With
the remainder now quoted it is told exactly what is wrong — "bar 1 is off by
7/8" — and still writes a bar that does not fill. Three attempts, three
failures, on a four-bar pop hook in 4/4. That is the one place in this review
where precise feedback demonstrably did not help, and it has no diagnosis yet.

The `double-fugue` and `kpop` re-runs ended on an exhausted API spending cap
rather than a musical failure, so the sibling fix is unmeasured on the piece
that motivated it. `Ascent` above is the evidence that exists.

## The pattern worth measuring next

Across all six completed pieces, the model is **consistently better at naming a
technique than at executing it** — tintinnabuli correct but an additive process
delivered as a sequence; polyptoton and melopoeia excellent but ekphrasis
invented in one piece and absent in another. And under load it satisfies the
mechanically checkable requests (rhyme) at the expense of the semantic ones
(description).

That is a harness question — does showing a worked example of a *technique*, as
`_motif_example` now does for notation, raise the rate at which it is realized?
— rather than a validator question, and it is not answered here.

## Reproducing

```bash
uv run cadenzra compose miniature
```

Any of the thirteen specs in `app/specs.py`. Each run writes its log to
`out/<spec>/runs/<timestamp>/` — `llm.jsonl` for verbatim prompts and responses,
`narrative.md` for the same flow with the model's reasoning, `technical.log` at
whatever `--log-level` asks for. Every diagnosis above came from reading those.

---

## Addendum — the lite-tier campaign (2026-08-10, evening)

After the cost audit's fix stack landed, the five unfinished probes were
re-driven on `gemini-3.1-flash-lite` for every capability (a deliberate dev
constraint: cost control, plus the weakest model as a stress instrument). The
campaign ran 48 resumed runs totalling 897 turns, ~1.69M input and ~250k answer
tokens — pennies at lite pricing, versus the audit's finding that a single
pre-fix probe could burn a spend cap. Every failed run cost a fraction of a
cent in seconds, wrote its salvage into `state.json`, and each `--resume`
started from everything already converged.

**The load-bearing result is not the pieces; it is the taxonomy.** Driving the
weakest model through the loops exposed twelve system faults that stronger
models had been papering over, each fixed test-first the same evening:

1. `rewrite_bars`' integer enum crashed the vendor type on the first live
   patch (the offline suite never constructed `types.Tool`).
2. A failure anywhere in the voice layer discarded every converged voice
   since the last layer boundary (`CadenzraError.partial_state` salvage).
3. LilyPond reports only the *first* failed bar check per compile, so serial
   discovery of several bad bars burned one attempt each (free reveal
   cycles: a patch that clears its offered bars pays nothing for what the
   next compile unmasks).
4. `_check_range` emitted one item per out-of-range *note* — ~80 for one
   stratospheric flute — flooding the repair prompt (now one item per bar
   and side, naming the count and the farthest offender).
5. Shown its rejected part under "change as little else as possible", the
   model re-emitted it nearly verbatim, mistake included (a rewrite whose
   feedback fingerprints equal what it was shown forfeits the copy and
   regenerates from scratch).
6. **"off by X" was the compiler's cursor position, not the deficit** — a
   hook holding 1/8 in 4/4 was told it was off by 7/8, and two model tiers
   chased that wrong number for seven attempts. The single worst feedback
   bug found to date.
7. The motif prompt named one meter for the whole batch while the validator
   checked each motif in its own declaring section's meter — an instruction
   no model could satisfy (metal-kpop's eight identical rejections, on the
   big tier and the small one alike).
8. Patches now declare their durations in a schema field the parser sums as
   exact fractions — the copy-reflex cannot pass an arithmetic gate — with a
   literal fix named when the sum misses ("add an r16"). The same
   declaration on whole parts was tried and reverted the same evening: on a
   16-bar part the model declared its 4-bar pattern and burned budgets on
   format, so the gate lives only where the evidence supports it.
9. A patch that repairs six of seven offered bars is not a failed patch;
   the fallback full rewrite no longer throws partial repairs away.
10. A motif entering a section in a foreign meter is now taught the tie
    technique (`4` becomes `8~ | 8`) exactly when the meters differ — the
    metal-kpop hook was mechanically unable to satisfy both the entry check
    and the meter check without it, and nothing had ever said so.
11. A pinned held tone that indicts the grid now loops back: the section's
    harmony regenerates once with the violation quoted before the run may
    go loud. The fresh double-fugue's Eb-over-G7 — the audit's motivating
    immortal violation — is exactly this class.
12. Two prescribed subjects that move in parallel octaves at their declared
    joint entry are rejected at motif time, before anything is built, using
    the same parallel-run math as the section checker.

**Where the pieces stand.** All five advanced from their spend-cap corpses to
within one voice of completion, and the walls that remain are model-capability
walls with varied (not repeating) failure signatures: metal-kpop (33 parts and
all seven lyric sections written, blinded craft review firing live) sticks on
vocal1's 7/8 breakdown bars; kpop (25 parts) on one Outro figuration voice;
orchestra (37 parts across five sections) on low-register discipline a
semitone below spec floors; longform cleared its inherited grid contradiction
through the regrid loop-back and is mid-Movement-III; double-fugue converged
compatible subjects under the new collision check and a grid that honors them,
and now walks the voice layer. `budget_exhausted` on the lite tier is an
accepted dev outcome — the pipeline's job is to be *honest* about it, and it
now is: every failure names its layer, its bar, and its true deficit.

**What the lite tier taught about feedback.** The constant-signature test is
the diagnostic to keep: when a failure repeats *identically* across attempts
(and especially across model tiers), it is the system lying to the model —
mislabelled deficits, contradictory instructions, information withheld. When
failures vary across attempts, it is the model, and budgets or better models
are the levers. Every one of the twelve fixes above began as a constant
signature.
