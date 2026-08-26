# Extensible and modular, but not prematurely abstracted

**Rule:** Aim for code that is easy to extend and modular, without abstracting before there's a reason to. The rule-of-thumb heuristic: *how much effort would it take to abstract this later?* If a lot — usually do it now (it's already complex and will only get worse). If a little — usually wait (you can do it cheaply the day a real need appears).

**Why:** Premature abstraction is a KISS failure (see [[keep-it-simple]]): it adds indirection for a flexibility nobody needs yet, and the wrong abstraction is harder to undo than no abstraction. But the opposite mistake — leaving genuinely complex, entangled code un-abstracted — is a time bomb that gets more expensive every time it's touched. The effort-to-abstract is a decent proxy: things that are hard to factor out are usually already complex enough to deserve the factoring, and things that are easy to factor out cost almost nothing to defer.

**How to apply:**
- Treat the heuristic as a starting point, not a law — reason about each case. Some real exceptions:
  - Some code has such an established pattern that the abstraction *is* the simple version (e.g. a Protocol boundary, see [[protocol-boundaries]]) — abstract even though it's easy.
  - Some code is hard to abstract because it's *already* abstracted to a high degree — adding another layer buys nothing; stop.
  - Some code is hard to abstract because the underlying design is bad. What it needs is a redesign/refactor, not a wrapper that freezes the bad shape in place.
  - Some hard-to-abstract code would gain no clarity or extensibility from abstraction — leave it inline.
- Don't abstract on speculation ("we might need two of these"). Abstract on demonstrated need, imminent need, or a clear, immediate gain in clarity.
- Keep things modular so a future refactor is cheap — that is different from doing the refactor now (see [[verify-before-moving-on]]).
