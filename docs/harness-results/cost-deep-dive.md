# The voice layer, dissected: the double-fugue autopsy and what it teaches

A companion to `cost-analysis.md`. That document located the spend; this one
explains the mechanism behind the largest sink — voice-layer correction — by
taking apart the most expensive run in the audit, turn by turn, and follows the
findings into design proposals.

Sources: `out/double-fugue/runs/20260810-094756/` (90 turns, 55.4 minutes,
8.3% of all audited spend, produced nothing), cross-checked against every other
run's logs and against `verification/section.py` at HEAD.

One timing fact frames everything: this run started at 09:47 and ran to ~10:43.
The sibling-visibility fix (`1e52f89`, 10:39) and the repair-accumulation fix
(`6207cb2`, 11:15) were committed *during and after* it — the process ran the
broken repair loop end to end. The re-run that would have measured the fixes
(`20260810-104436`) died on the spend cap. So this autopsy is of known-bad code,
and part of its value is confirming exactly *which* of the five mechanisms below
the committed fixes address — two of them — and which three are still live at
HEAD.

## Part 1 — Why the first pass was "horribly wrong" (it mostly wasn't)

The run's shape: turns 11–36 generated all six sections' voices, with only two
local retries. Then the section-level cross-voice check fired with **263
messages**, and three global repair sweeps (turns 37–57, 58–74, 75–90) consumed
the remaining 40 minutes without converging: 263 → 63 → 66.

Three corrections to the headline number:

**First, the count is ~5× inflated.** `_parallels_between`
(`verification/section.py:128`) emits one `FeedbackItem` per consecutive
attack pair. Four eighth-notes of parallel motion = three violations. The
sweep-1 messages collapse from 207 parallel events to **~44 distinct
passages**. The model was told "239 things are wrong" when perhaps 44 were —
and each repair prompt concatenated every complaint routed to that voice
(max observed: 45 in one prompt).

**Second, the entries were nearly perfect.** Sweep 1 contains exactly *one*
subject-entry violation across fourteen prescribed entries. The model, asked to
reproduce a subject note for note at a stated bar, did it. The first pass
failed almost entirely on one thing: **cross-voice relationships between
independently written lines.**

**Third, that failure was predictable from the architecture, not a model
weakness.** First-pass voices are generated concurrently and independently
given the skeleton (docs/04). Coordination is the harmony grid — which
constrains *pitch class*, not *motion*. Four voices drawing from the same chord
tones with the same rhythmic cells will produce parallel octaves at a high
base rate; nothing in any prompt could have prevented it, because no voice knew
what any other voice was playing. Independence-given-skeleton is cheap and
correct for homophony. For imitative counterpoint — where the *relationships*
are the content — it manufactures the violations that the most expensive
repair loop then fails to fix.

## Part 2 — Why it never converged: five stacked mechanisms

Measured trajectory: 263 → 63 → 66, with **9 violations surviving all three
sweeps verbatim**. Non-convergence had five distinct causes, and they compound.

### 2a. Repairs were blind (fixed at HEAD, unmeasured)

Sweep-1 repair prompt to the cello, verbatim: *"cello and viola move in
parallel octaves into bar 6, beat 4; approach the second one by contrary or
oblique motion"* — with the viola's line nowhere in the prompt. Contrary to
*what*? The cello was asked to fix a relationship to a line it could not see.
`1e52f89` fixed this; the fix has never run against this piece.

### 2b. Both voices of a pair moved at once against a stale snapshot (fixed at HEAD, unmeasured)

All ~20 repairs in a sweep were generated from the same pre-sweep state. Where
a complaint *was* delivered to both voices, both moved blindly and
re-clashed differently — which is why sweep 2's violations are 57% *new*
messages, not survivors. `6207cb2` fixed accumulation; also unmeasured here.

### 2c. Pair violations route alphabetically — still live at HEAD

`_check_parallels` sorts voice names and `_parallels_between` assigns every
pair violation to `voice_id=upper_name` — the alphabetically first voice
(`section.py:109,141`). "cello and viola", "cello and violin2": every complaint
lands on the cello. Confirmed in the log: the viola's own sweep-1 repair prompt
contains **zero** cello-pair complaints. The cello — in a fugue exposition the
most *prescribed* voice — silently absorbed the entire repair burden for every
pair it appears in, while its counterpart was never told anything was wrong.

### 2d. Two validators issued contradictory orders — still live at HEAD

The repair prompt says *"Fix these problems, changing as little else as
possible"* and flags bars 1–2. The entry check demands bars 1–2 match the
subject **note for note**. The model obeyed the repair prompt — and sweep 2
promptly reports **eight** entry violations where sweep 1 had one, at exactly
the bars sweep-1 repairs touched. Sweep 3 then repaired the entries back,
recreating parallels. The loop oscillated between two validators, each undoing
the other's demand, spending ~13 minutes per cycle. Neither check knows the
other's constraints; nothing excludes a prescribed span from repair, and
nothing routes a complaint *away* from the voice that is not free to move.

### 2e. The plan itself was self-contradictory — no check exists, at any layer

The deepest cause. The three violations that survived all three sweeps in the
same words are all the same fault:

> cello holds D#4 through bar 1/2, beat 3, where the harmony is G7/B / G/B / C7/E

D#4 is the MIDI spelling of **E♭ — the third scale degree of C minor, beat 3 of
the fugue subject itself** (`… ees'4. d'8 | … ees'4 c'4`). The structure layer
prescribed a subject with E♭ on beat 3 *and* a harmony grid with a G-major- or
C-major-family chord under that same beat, in three different sections. The
subject cannot change (the entry check pins it); the harmony cannot change (no
feedback path reaches it from here); the violation is **unfixable at the voice
level by construction**, and the run duly spent three sweeps not fixing it.

This violates the project's own first rule — *"a fix loops back to the layer
that owns the mistake."* The mistake is owned by `plan_structure`/`write_harmony`;
it was detected three layers downstream and routed to a voice that had no
degree of freedom left. Checking motif-against-grid consistency at plan time is
deterministic (transpose the motif to each declared entry, compare pitch
classes against the grid chord — no LLM, no compile) and would have failed this
plan in milliseconds for free.

A surface bug compounds 2e: the message spells the pitch `D#4`
(`Pitch.to_scientific()` from MIDI, `section.py:237`) while the model wrote
`ees'` and the piece is in C minor. Per CLAUDE.md the musician surface is the
only language prompts may speak; a voice hunting for a D-sharp it never wrote
is a small extra tax on every held-tone repair.

### What this means for the committed fixes

Sibling visibility (2a) and accumulation (2b) attack real mechanisms, but the
autopsy says they were *not sufficient* for this piece: 2c starves half of each
pair of its feedback, 2d makes some repairs mandatory-and-forbidden, and 2e is
unfixable downstream no matter how good the repair loop gets. Expect a re-run
to do better and still fail. Fixes for 2c–2e are prerequisites for the
double-fugue to ever complete.

## Part 3 — Structural changes to cut voice-layer cost

Cross-run context (all 34 runs): of voice-layer regeneration spend, **61.0% is
cross-voice repair**, 16.8% range, 11.2% entry, 6.4% meter, 3.1% compile. The
local per-voice loop (range/meter/compile) is cheap and converges; the money is
entirely in the relationship checks. In order of expected value:

**1. Write contrapuntal voices sequentially, with the finished lines in
context.** For textures the structure plan marks imitative/contrapuntal,
generate voices in entry order, each seeing the already-written lines. This is
how counterpoint is actually written: against a fixed cantus, not into a void.
Cost: sibling notation adds ~200–400 input tokens per voice — call it +30% on
first-pass voice input, ≈ +4% of total spend. Return: it attacks the checks'
base rate at the source; even halving cross-voice regen repays that several
times over, and it removes the concurrency that mechanisms 2a/2b exist to
patch. Keep concurrent-independent generation for homophonic textures — the
texture field already exists on the section plan, so this is a branch on data,
not a redesign. (It does trade away within-section parallelism and batch
eligibility for these sections; that latency is the price of not buying three
repair sweeps.)

**2. Repair by patch, not by rewrite.** Today a repair regenerates the whole
part (median ~510 thinking + full part output, every time). Instead, offer an
edit surface: "rewrite bars 6 and 9–10 only", schema returns only replacement
bars, deterministic splice. Three savings at once: output shrinks to the
changed bars; thinking shrinks with the task; and **prescribed bars are simply
not offered for editing**, which kills mechanism 2d structurally instead of by
exhortation — the model *cannot* break an entry it is not allowed to touch. If
every flagged bar in a span is prescribed, the item is unfixable at voice level
and should escalate instead of burning budget (that's 2e made loud).

**3. Route pair violations to the freer voice, and dedup runs of events.**
Replace alphabetical assignment with: never route to a voice inside a
prescribed span; prefer the voice with fewer total complaints; when both are
free, tell *both* (the sibling fix means each now sees the other's line).
Collapse consecutive same-pair events into one span message ("parallel octaves
through bar 1 beats 1.75–2.5"). Both are small pure-code changes in
`section.py`; together they turn 45-complaint prompts into ~9-complaint
prompts aimed at voices that can act.

**4. Check plan consistency at plan time.** Deterministic motif-vs-grid check
at every declared entry, run inside the `plan_structure`/`write_harmony`
convergence loops, feeding back to the layer that owns the contradiction. Costs
no tokens at all; would have saved this run's entire 55 minutes, and the
`metal-kpop` motif mystery (still open in the quality review) smells like the
same class.

**5. Convergence guard on the section loop.** The run's trajectory 263 → 63 →
66 stalled at sweep 2; sweep 3 (~18 turns, ~13 min) was spent learning what
sweep 2 already proved. When the distinct-violation count stops falling,
stop — either escalate (per docs/05 routing) or fail. One comparison, one
early exit.

**6. Spell feedback pitches on the musician surface.** `ees'`, not `D#4` — use
the key signature to choose the spelling, quote the note as the voice wrote it.

These compose: 1 lowers the violation base rate, 3+6 make the remaining
complaints actionable, 2 makes each repair cheap and safe, 4 removes the
unfixable class, 5 stops paying for proven stalls. Note that none of them
require deciding the "is the counterpoint checker in scope" question raised in
`cost-analysis.md` — they make the checker affordable either way, though that
question stands.

## Part 4 — `review()`: unintentionally left out, not dead code

Verdict: **planned, fully built, never wired — and the docs say it runs.**

The evidence, end to end: the protocol slot dates to M2 (`4aa8aee`) and every
supporting piece exists at HEAD — `model/review.py` (`ReviewRequest`/
`ReviewVerdict`), `review_schema()` in `llm/schemas/structured.py:308`,
`parse_review_verdict` in `llm/parsers/structured.py:203`, a live
implementation in `gemini_generator.py:209`, and fake support in
`tests/fakes/generator.py:123`. The Part B plan explicitly called for "the
dormant `review()` slot finally used, asking narrow craft questions" in
`_lyrics_to_convergence`, and `docs/10-lyrics.md:62` describes the craft review
in the present tense. The single missing piece is the call site. Four artifacts
built, the fifth line never written — an implementation gap from the Part B
push, not a decision.

Two honest options, either of which is fine and both of which beat the status
quo:

- **Wire it** as designed: one blinded craft question per section in
  `_lyrics_to_convergence`, advisory-within-budget like the device check.
  Marginal cost ~1 call/section (the audit's whole critic line was 0.5%).
- **Cut it**: delete the protocol method, model, schema, parser, impl, and fake
  support, and correct docs/10. Zero-cost code is still code to read
  (keep-it-simple), and the blinded *device* observer already covers part of
  the ground.

What is not fine is the current state, where the design doc asserts a check
that never runs — a reader auditing lyric quality would believe a safeguard
exists that doesn't.

## Part 5 — Observability: what the logs should record

This audit took a day of scripted reconstruction because the logs record
*conversations* faithfully but record almost no *accounting or lineage*. Every
item below earns its place by naming the question it answers that this audit
had to answer the hard way — ordered by how much this audit needed it.

**Per turn (`llm.jsonl`):**
- **`usage`: the full `usage_metadata`** — prompt, response, *thinking*, and
  *cached* token counts. Thinking summaries understate billed reasoning by an
  unknown factor; cached-token counts are the only way to learn whether implicit
  caching fires at all (the cost analysis suspects it never does). This field
  alone converts every estimate in both documents into a measurement.
- **`finish_reason` and any `model_version` the API reports** — a truncated
  response and a silently upgraded model are currently indistinguishable from
  a bad answer. Plus `request_id` for support escalation.
- **`purpose: "first" | "repair" | "retry"` and, for repairs, the ids of the
  feedback items being addressed** — reconstructing first-vs-correction spend
  required re-deriving occurrence order for 1,209 turns; one enum field makes
  it a `grep`.

**Per validation event:**
- **Structured items, not prose strings**: `{kind, section, voices, bar, beat,
  span, message}`. Cross-sweep survival analysis (the 9 immortal violations)
  had to match verbatim strings; a stable identity (kind+voices+location) makes
  convergence-vs-plateau a computation. The prose stays — it is the prompt
  surface — but as a field beside the data, not instead of it.
- **The routing decision**: which voice each item was assigned to and why.
  Mechanism 2c (alphabetical routing starving half of each pair) was invisible
  in the logs; it had to be found by diffing prompts against the checker source.

**Per run (new `summary.json`, written by the same `_write_partials` path so
failures get one too):**
- **Git SHA (+dirty flag), full resolved config, and the spec content** — the
  most consequential fact about run `094756` (it ran pre-fix code) was
  established by comparing wall-clock times against `git log`. Runs during
  active development are meaningless without provenance. The spec matters for
  the same reason: `out/<spec>/state.json` is overwritten by every re-run, so
  this forensic had to recover run 094756's structure plan from its `llm.jsonl`
  after the state was clobbered. **Copy `state.json` into `runs/<ts>/` as
  well** — artifacts stay at `out/<spec>/` per the layout decision; the run dir
  gets the forensic copy.
- **Convergence trajectories**: per loop, the violation count (raw and
  deduplicated) per attempt — `263 → 63 → 66` should be one line to read, not
  an evening to compute. This is also what recommendation 5 in Part 3 consumes.
- **Stage totals**: turns, tokens by category, seconds, retries, regen counts
  per stage; end status (`completed | budget_exhausted | crashed | spend_cap`)
  with the terminal loop named. The `EXIT:1`s in the probe table each cost a
  log-reading session to attribute.
- **Dollars**: a small price table in config (per-model input/output/thinking
  rates), applied at summary time. Approximate is fine; visible is the point.

**Separate concerns worth naming:**
- **Backoff vs latency**: today the logged `seconds` would silently include
  rate-limit sleeps (the sleep happens before `_record`). Log waits as their
  own events; a run stalling on quota should be legible as such.
- **A tiny cross-run index** (`out/index.jsonl`, one summary line per run):
  spec, timestamp, SHA, status, tokens, dollars. The question "what has all of
  this cost this month" should not require a filesystem walk.
- **Keep narrative.md as is** — it was the most useful artifact in the audit
  and needs nothing.

The through-line of all five parts: the run log was built to audit *what the
model was told*, and it does that superbly — every mechanism in Part 2 was
provable from stored prompts. What it cannot yet do is audit *what the system
did about it*: route, count, converge, spend. That half is cheap to add and
would have turned this two-day forensic into an afternoon.
