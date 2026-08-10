# 10 — Lyrics

This is the fifth big complexity purchase, and [08](08-engineering-principles.md) principle 1 says it gets its own written justification before it gets written. Here it is.

## Why the one-sentence version failed

Lyrics were, until this doc, a single conditional in the voice prompt: *"This part is sung: also write the lyrics as a `\lyricmode` block."* Everything else about lyrics was a storage field and a compiler warning.

Two structural facts made that untenable, both observed in real runs:

**Voices sing past each other.** Voice parts were generated concurrently within a section (homophonic textures still are; contrapuntal ones have since gone sequential — docs/04), each with a `VoiceContext` that contains no other voice's text. Four singers each invent a text independently, and nothing in the system says otherwise — one run produced a piece where one voice sang in Latin while another sang English over the top of it. `PieceSpec.language` existed the whole time and was read by nothing. Coordination is not a quality problem to be prompted away; it is missing by construction.

**"Write the words too" is not a task the music layer can hold.** A voice prompt already carries the meter, the range, the harmony, the motif entries, the dynamics and the fragment contract. Asking the same call to also serve a story, a rhyme scheme and a set of rhetorical devices means one of the two gets the model's attention. And the words that fit a melody can only be written once the melody exists.

So lyrics become what every other hard thing in this system is: a layer of its own, planned coarsely near the top, realized finely at the bottom, and verified at the level it was produced ([04](04-generation-layers.md)).

## The two layers

**`plan_lyrics`** runs immediately after `plan_structure`, and is skipped entirely for instrumental pieces. It produces a `LyricPlan`: a language, a story for the whole piece, and one `SectionLyricDirective` per singing section — a story beat, requested devices from a controlled vocabulary, a rhyme scheme, a voice relationship, and optionally a refrain link to an earlier section. This is the plan-level *brief* pattern that `MaterialBrief` already establishes: say what must be produced and for whom, before anything is elaborated, so that it can be checked while it is still cheap.

**`generate_lyrics`** runs after a section's voices have converged and before assembly, once per section, in **one call covering every singing voice at once**. That is the whole coordination mechanism: a single call cannot produce two languages any more than a single writer can, and duet, canon, call-and-response and melody-with-harmony are relationships between texts that only exist if one mind writes both. Its context is the section's realized notation verbatim, the preceding sections' lyrics, and the directive.

Two consequences worth stating plainly:

- **Words follow music.** The notation is the source of truth; lyrics are fitted to it. When cross-voice verification rewrites a voice's music, that section's lyrics are regenerated after it — a downstream artifact rebuilt from its source, exactly as the audio is.
- **This breaks the intra-section fan-out symmetry**, deliberately. [04](04-generation-layers.md) already sanctions ordering dependencies where texture creates them ("unison" generates one rhythmic surface first and constrains the others); coordinated text is the same case, and lyrics are one call rather than an ordering because partial coordination is not coordination.

## Who decides what

Three owners, and the boundaries are the point.

**The compiler owns note/syllable alignment.** LilyPond warns when a `\lyricmode` block does not line up with the notes it is set to. That answer is already correct, already free, and already quoted into feedback. Counting syllables in Python and comparing them to a note count would be a second, worse implementation of a check we already have — the same trap [08](08-engineering-principles.md) names when it rejects cross-checking the `techniques` list against notation markup.

**Deterministic checks own declared contracts.** Everything the plan *stated* is arithmetic:

- rhyme-scheme adherence — do the lines the scheme marks `A` actually rhyme?
- unison relationship — do the voices sing identical text?
- refrain — does the section that declared itself a refrain of an earlier one reuse its words?
- plan well-formedness — do directives cover the singing sections, are devices in the vocabulary, does a refrain point at a section that already happened?
- language — one language for the piece, stated once, in the prompt of every lyric call.

**The LLM owns craft.** Whether a chiasmus actually landed, whether the prosody sits well, whether these lines continue the previous ones — none of that is decidable, and all of it is worth asking about.

**What is deliberately not built:** a stress-versus-meter engine. It is tempting: CMUdict gives stress patterns, note durations give strong and weak positions, and the two could be compared. But that comparison decides *whether the setting is good*, and [01](01-vision-and-scope.md) rules out exactly this — a general music-theory engine, here in poetic dress. Deliberate prosodic dissonance is a technique, not an error; a validator that flagged it would legislate taste and be wrong about the most interesting writing in the piece. Alignment belongs to the compiler, prosody to the reviewer's judgment. The door stays open; walking through it is a stated choice.

## The rhyme module

`verification/rhyme.py` answers one question: **does the stated scheme hold?** Never "is this a good rhyme" and never "should this have rhymed".

It uses CMUdict (via `pronouncing`) rather than a hand-rolled syllabifier, following [05](05-verification-and-feedback.md)'s "prefer existing tools over new parsers". A rhyme key is the phone sequence from the last stressed vowel of a line onward, built from the trailing words concatenated — which is what lets mosaic and multi-word rhymes ("poet know it", "bought a pear / daughter, fair") satisfy a scheme rather than fail it. Words the dictionary does not know are skipped rather than failed: an invented word, a proper noun or a loan word is not evidence of anything.

CMUdict is English-only. `LyricsSpec.language` gates the deterministic path; other languages fall back to LLM review, which is a real reduction in strength and is stated here rather than hidden. Enforcing a scheme is a promise the system can keep in English and can only advise on elsewhere.

Internal rhymes, holorimes and the rest of the flexible cases are *requestable* as devices and reviewed by the LLM. Only the line-end scheme is enforced deterministically, because only it has an unambiguous contract.

## Not giving the judge the answer key

[05](05-verification-and-feedback.md) records what happens when an LLM judge is told what it is supposed to find: it finds it, present or not. The audio critic confabulated an entire dynamic arc in a performance that had none.

The same failure mode is waiting here, and would be worse: "did this realize an objective correlative?" asked of a model that has been told an objective correlative was requested is not a question, it is a prompt. So device verification runs blind. `observe_lyric_devices` sees the lyrics and the **complete** device vocabulary — never the requested subset — and reports what it observes. The comparison against the directive happens in our code, on values the model never saw. A device the plan asked for and the observer did not notice becomes advisory feedback, not a veto.

The craft review (the general `review()` slot) likewise asks about coherence and awkwardness without naming the theme, the devices or the scheme.

## Routing and failure

Lyric feedback is a new `FeedbackItem` level, `lyric`, sitting between `interpretation` and `voice` in the cheapest-first cost order: regenerating a section's words touches no notation, so it is strictly cheaper than regenerating a part.

Feedback routes back to `generate_lyrics` for that section and nowhere else. In particular there is **no automatic escalation from lyrics to music** in v1. If words cannot be made to fit a line within the budget, the run fails loudly with partials rather than rewriting music that passed every deterministic check on the strength of a lyric complaint — that is the weakest-evidence cascade [05](05-verification-and-feedback.md) warns about, and melismas make alignment satisfiable in nearly every real case. If measurement later shows otherwise, the escalation is one edge to add.

LLM verdicts follow the standard rule: they may send work back within budget, but never veto a final attempt that is deterministically clean.

## The surface

Lyrics come back as **lines of lyricmode-convention text**, one list per voice:

```
"sha -- dow of the wa -- ter, and the light __"
```

Not a JSON tree of syllables with stress annotations. Hyphenated `\lyricmode` is textbook LilyPond — the highest-density representation the model has for this task — and a structured syllable tree would be the lowest, sitting exactly where quality is decided ([08](08-engineering-principles.md) principle 2). This is the same argument that keeps notation as notation.

Lines are the unit because they are what rhyme schemes, refrains and coordination are stated in. Our parser tokenizes them (whitespace split, `--` joins, `__` melismas) and renders the final `\lyricmode` block itself. That tokenization is a token scan, not a parser — the same allowed class as counting `|` in a fragment — and it never interprets the notation.

Stray `|` are stripped, as they already are: inside `\lyricmode` a barline is a bar check, and a model mirroring the music's barlines into its text writes checks that pass in a single-section scaffold and fail once sections are concatenated.

## Device vocabulary

Devices are a controlled vocabulary, not free text, so that a directive can be checked and an observation can be compared:

`objective_correlative`, `melopoeia`, `zeugma`, `anacoluthon`, `polyptoton`, `ekphrasis`, `chiasmus`, `anaphora`, `epistrophe`, `apostrophe`, `synesthesia`, `internal_rhyme`, `mosaic_rhyme`, `holorime`, `prosodic_dissonance`, `refrain`, `volta`.

Capability gating applies ([08](08-engineering-principles.md) principle 2): the vocabulary and its definitions appear in a prompt only when the piece activates lyrics, and an instrumental spec never sees a word of it.
