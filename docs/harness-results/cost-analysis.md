# Where the spend cap went

An audit of all 34 logged runs (1,209 LLM turns) across the eleven probe specs,
reconstructed from `out/*/runs/*/llm.jsonl`.

## Method, and what to distrust

`GeminiClient` never reads `usage_metadata`, so **no token counts were ever
recorded**. Everything here is reconstructed from the logged text: every system
prompt, user prompt, thought summary and tool response is stored verbatim, so
the reconstruction is complete in coverage even though each count is an
estimate (4 chars/token for prose, 3 for LilyPond and JSON payloads).

Three caveats, stated up front because they change how much weight each number
carries:

1. **Absolute token counts carry roughly ±15%.** The *shares* between layers are
   much firmer — every turn is measured by the same ruler, so systematic error
   largely cancels when comparing one stage against another.
2. **Thinking tokens are a floor, not a measurement.** `include_thoughts=True`
   returns thought *summaries*; the model is billed for the full reasoning trace,
   which is larger. Every "thinking" figure below understates the real cost.
3. **"Weighted" means input + 8×output**, output being the more expensive side.
   The headline conclusions are insensitive to this: at 3×, 4×, 8× and 12×, the
   voice layer stays at 60–64% of spend and thinking stays at 52–65%.

Measured totals: **931,011 input tokens, 602,084 thinking-summary tokens,
247,790 answer tokens.**

## The headline: the pieces were not the expensive part

| | share of all spend |
|---|---|
| The 6 pieces that actually completed | **22.8%** |
| Everything else — failed runs, aborted runs, re-runs, smoke tests | **77.2%** |

Split a different way, by whether a run was the first attempt at its spec:

| | weighted | share |
|---|---|---|
| First attempt at a spec | 1,582,606 | 20.5% |
| **Re-runs of a spec already attempted** | **6,147,397** | **79.5%** |

`orchestra` ran 4 times, `kpop` 5, `double-fugue` 4, `metal-kpop` 6. Every one of
those re-runs restarted at `describe_style` and rebuilt the entire piece,
because **there is no resume path**. `_write_partials` (`app/compose.py:929`)
serializes the complete `PipelineState` to `state.json` on success *and* on
failure — and nothing ever reads it back. A run that died in the last section's
cross-voice check threw away a settled style, structure, motif set, harmony plan
and every completed section, then paid for all of it again.

Within re-runs, 26.3% went on re-deriving scaffolding layers (style, structure,
motifs, harmony, lyric plan) that had already succeeded in a previous run.

## Where it went inside a run

| stage | turns | input | thinking | answers | share |
|---|---|---|---|---|---|
| voices | 768 | 704,578 | 392,036 | 110,140 | **61.1%** |
| harmony | 141 | 49,760 | 73,668 | 50,153 | 13.5% |
| lyrics | 98 | 88,972 | 46,547 | 15,540 | 7.6% |
| structure | 33 | 13,265 | 22,435 | 36,710 | 6.3% |
| style | 80 | 26,203 | 18,056 | 15,811 | 3.8% |
| device observation | 33 | 17,747 | 16,923 | 5,081 | 2.5% |
| motifs | 33 | 15,675 | 18,173 | 4,033 | 2.5% |
| lyric plan | 16 | 12,608 | 10,665 | 9,604 | 2.3% |
| audio critic | 7 | 2,203 | 3,581 | 718 | 0.5% |

`write_part` is 63% of all turns and 61% of all spend. Any optimisation that
does not touch the voice layer is rounding error.

## Original generation vs correction

| | turns | weighted | share |
|---|---|---|---|
| First pass | 814 | 5,721,054 | 74.0% |
| Validator-driven regeneration | 301 | 1,943,373 | **25.1%** |
| Malformed-output retry (client-level) | 94 | 65,576 | 0.8% |

Correction is a quarter of in-run spend, and it is very unevenly distributed:

| stage | correction share |
|---|---|
| device observation | 71.9% |
| lyrics | 44.6% |
| voices | 30.1% |
| motifs | 28.9% |
| structure | 18.9% |
| style | 5.1% |
| harmony | 2.3% |

The client-level retry loop (`llm_attempts=3`, for malformed responses) is
almost free at 0.8% — that machinery is not a cost problem. The expensive
correction is the *validator* loop, which regenerates well-formed music that
failed a musical check.

**A lever that looks real and is not:** regeneration depth. One voice was
regenerated 12 times, which is alarming to read in a log, but everything at
attempt 4 or deeper is only **6.3% of the voice layer**. Capping the loop at 3
would save under 4% of total spend and would lose the 55% of 4th attempts that
do succeed. Not worth doing for cost reasons.

## Reasoning: 71% of output, no measurable benefit at the voice layer

Thinking summaries are **602,084 of the 849,874 output tokens — 71%** — and
that is a floor, since summaries are shorter than the billed trace.

Does it help? At the voice layer, turns can be sorted into those that were
accepted and those a validator sent back:

| | n | median thinking |
|---|---|---|
| Accepted (final) turns | 508 | 556 tok |
| Rejected turns | 188 | **589 tok** |

**Rejected turns think slightly more than accepted ones.** This is confounded —
harder bars plausibly draw more reasoning — but that confound cuts the same way
either time: if extra thinking rescued hard cases, the rejected group would think
more *and* the effect would show up as a lower rejection rate somewhere. It does
not. There is no signal here that unbounded reasoning is buying correctness on
`write_part`.

Thinking-to-answer ratio by stage, which is where the waste concentrates:

| stage | thinking / answer |
|---|---|
| audio critic | 5.0× |
| motifs | 4.5× |
| voices | 3.6× |
| device observation | 3.3× |
| lyrics | 3.0× |
| harmony | 1.5× |
| style | 1.1× |
| structure | 0.6× |

`structure` at 0.6× is the healthy shape: a planning task that produces a large
structured answer. `motifs` at 4.5× is spending four times more on deliberation
than on the one-line melodic cell it emits.

One correction to a natural assumption: **turning off `log_thoughts` saves
almost nothing.** `include_thoughts` controls whether summaries are *returned*,
not whether the model reasons. When it is false, `thinking_config` is set to
`None` (`gemini.py:108`), which means default dynamic thinking — the tokens are
still spent, and you lose the narrative log that makes failures diagnosable. The
lever is an explicit *thinking budget*, not the summary flag.

## Evaluators are cheap directly, expensive indirectly

| | direct share |
|---|---|
| Device observation | 2.51% |
| Audio critic | 0.47% |

The audio critic ran only 7 times in 34 runs and is negligible. The dormant
`review()` slot was never called — it costs nothing because it is still unwired.

But direct cost understates them. Device observation is 2.5% of spend and is
**71.9% regeneration itself**, and it drives the lyric layer's 44.6% correction
rate. An evaluator that costs 2.5% while triggering rework in a layer that costs
7.6% is worth judging on the combined figure, not its own line.

## Caching: 66% of voice input is re-sent text that cannot be cached

System prompts: 359,594 chars sent, 51,171 unique — **85.8% redundant**. But
system prompts are only ~10% of input, so this is a small prize on its own.

The real prize is the voice user-prompt, 2,604,378 chars across all runs:

| | share of voice input |
|---|---|
| Piece-wide repeated content (style, cells, fragments, notation conventions) | 46.3% |
| Section-wide repeated content (meter, harmony grid, texture, dynamics) | 19.4% |
| **Total that could sit in a shared cache prefix** | **65.7%** |

None of it currently can, because of prompt *ordering*. A `write_part` prompt
opens with the single most voice-specific line in it —

```
line   0 | Write the violin2 part for this section.
line   7 | Range for violin2: G3 (g) up to C6 (c''').
line   9 | Style: ...                          <- piece-wide
line  15 | Rhythmic cells for 4/4 ...           <- piece-wide
line  25 | Harmony to write against: ...        <- section-wide
line  46 | Write the part under these conventions:  <- piece-wide, ~1000 chars
```

— so the common prefix across two voices in the same section is essentially
zero. Measured directly: only **6.0%** of user-prompt content is currently a
shared prefix.

Worth noting separately: the ~1000-character notation conventions block (Dutch
note names, explicit durations, bar checks, the structural-command denylist) is
in the **user** prompt on all 768 voice calls, while the `write_part` system
prompt is a 280-character sentence. That block is invariant for the entire
project. It is a system prompt that is being paid for as a user prompt.

## What to do, in order of size

**0. Record `usage_metadata`.** Everything above is an estimate because the
client discards the token counts the API already returns. Three lines in
`GeminiClient._record` plus three fields in `RunLog.llm_turn` turns this whole
document into a measurement next time. Do this first, or the effect of every
other change below stays unmeasurable.

**1. Resume from `state.json`. (addresses 79.5%)** The state is already
serialized on failure and already round-trips through Pydantic — there is an
integration test asserting it. A `compose --resume <spec>` that loads the last
partial and skips every layer already present would have cut the largest single
line item in this audit to near zero. This is the highest-value change in the
project by a wide margin, and it is mostly plumbing.

**2. Replay one turn from the log. (addresses most of the same 79.5%)** Most
re-runs existed to test a *prompt fix*, not to get a different sample. The log
already stores the exact `system_prompt`, `user_prompt` and tool name for every
turn, including every failure. A `cadenzra replay <run> <seq>` that rebuilds the
prompt from current code and fires that single turn would let a prompt change be
evaluated for one call instead of one piece. During Part C this alone would have
replaced several forty-minute, full-price runs with a few seconds each.

**3. Set an explicit thinking budget. (addresses ~42% of output tokens)** If
thinking were capped near answer size, output tokens drop 42%. Given that
rejected turns already think *more* than accepted ones, the quality risk at the
voice layer looks low — but this is the one recommendation that could plausibly
cost quality, so it should be measured, not assumed: run the existing
`harness voice` A/B at two or three budgets and read the pass rate. Start with
`motifs` (4.5× ratio, one-line output, 2.5% of spend) as the cheap pilot before
touching `voices`.

   *Deferred by decision (2026-08-10): postponed for its quality risk. Revisit once `summary.json` makes the effect measurable against real usage numbers.*

**4. Reorder prompts so the invariant part comes first. (addresses 65.7% of
voice input)** Move the notation conventions block into the `write_part` system
prompt where it belongs, then order the user prompt piece-wide → section-wide →
voice-specific. This is a pure win independent of caching: it shortens what the
model has to read past. With caching it becomes much larger, since a stable
prefix is what implicit caching keys on. Two things to check against current
Gemini docs before relying on it: the minimum prefix length for implicit caching
(voice prompts are ~700–1,000 tokens and may currently sit under it, which would
mean caching is not firing *at all* today), and whether explicit cached content
is worth its storage cost for a run that lasts under an hour.

**5. Tier the models.** Both roles currently point at `gemini-3.6-flash`
(`config.py:19-20`) — there is no tiering at all today. The data suggests moving
in *both* directions rather than uniformly down:

- *Down:* `describe_style` (3.8%, formulaic, 5.1% correction rate) and
  `observe_devices` (2.5%, a classification task) are the safe candidates.
  Combined they cap out around 6% of spend, so this is a modest prize.
- *Up:* the voice layer is 61% of spend with a 30% correction rate. If a stronger
  model cut voice regeneration from 30% to 15%, it would save more absolute spend
  than downgrading every cheap layer combined. Worth an experiment before
  assuming the cheap direction is the frugal one.

**6. Batch inference for first-pass voices. (42.7% of spend is eligible)**
First-pass `write_part` calls within a section are independent by construction —
they already fan out concurrently. That is 3,300,898 weighted tokens, 42.7% of
all spend, structurally eligible for a batch endpoint at roughly half price. The
catch is latency: batch turnaround is unsuitable for the interactive
compose-and-correct loop. It fits the *probe matrix* workflow exactly, though —
running ten evaluation pieces overnight has no latency requirement.

   *Deferred by decision (2026-08-10): postponed. Resume, replay and the voice-layer structural fixes land first; revisit once their effect on first-pass volume is measured.*

## Indirect levers, which are the largest ones here

**The cheapest piece is the one you do not re-run.** 77.2% of this audit bought
nothing that shipped. Almost none of that was model inefficiency; it was
*workflow*: no resume, no single-turn replay, and prompt iteration validated by
full live runs. Items 1 and 2 above are worth more than every token-level
optimisation in this document combined, and neither is a prompt change.

**Fail early rather than loudly-but-late.** The most expensive single run in the
audit — `double-fugue`, 8.3% of all spend, 55 minutes — spent 63.5% of itself on
correction and produced nothing. Its cross-voice check emitted **70 violations
concatenated into one feedback string**, then sent that string to every voice
being repaired (max observed: 45 complaints in a single prompt, pushing it from
686 to 987 tokens). A voice asked to fix 45 relationships at once will not fix
45 relationships. Two changes, both cheap: cap the number of complaints carried
into one regeneration prompt and prioritise them, and abandon a section when the
violation count fails to *fall* between attempts. The 9 → 0 → 1 trajectory
already recorded for `orchestra` in the quality review is what convergence looks
like; 239 → 48 → 48 is a plateau that should have stopped at the second reading
rather than spending its full budget.

**Question whether the counterpoint checker is in scope.** This is a design
question with a large cost attached, not just an accounting one. `CLAUDE.md`
says checks decide "arithmetic, ranges, and declared relationships" and that
docs/01 rules out a general music-theory engine. Subject-entry checking is
clearly a declared relationship — the spec asked for a fugue subject at a stated
bar. But parallel fifths and octaves, and unresolved held tones against the
harmony grid, are closer to taste than to declared contract, and they generated
the overwhelming majority of those 70 complaints. They are the single largest
source of correction spend in the most expensive runs. If they stay, that should
be a stated decision with the cost acknowledged; if they go, `double-fugue` and
`orchestra` likely complete.

**Stop paying for smoke.** Three `smoke` runs cost 4.5% of the audit, and one of
them ran at 52.7% correction. Development-loop verification against the live API
is a recurring cost with no artifact; the existing fake-generator path should
absorb more of it.

## Summary

The spend was not drained by expensive music. It was drained by **doing the same
work repeatedly**: 79.5% on re-runs of specs already attempted, 25.1% on
in-run correction, and 71% of every output token on reasoning that shows no
measurable benefit where it is most heavily spent. The three fixes that matter —
resume, single-turn replay, and an explicit thinking budget — are all
straightforward, and none of them require compromising the "fail loud, never
produce a plausible-but-wrong score" guarantee that the retry budgets exist to
protect.
