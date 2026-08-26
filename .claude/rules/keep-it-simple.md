# Keep it simple; complexity is a deliberate, stated choice

**Rule:** Default to the simplest solution that is correct, robust, and performant. Every step away from simple — toward cleverness, advanced constructs, or extra scope — must be a conscious tradeoff you state out loud, never a default you drift into. The simplest code a beginner could follow is the ideal; depart from it only with a reason.

**Why:** This project has genuinely hard demands, so complexity is often unavoidable — which is exactly why it has to be rationed. Unjustified complexity and scope creep are the main sources of bugs and maintenance cost, and they accumulate silently if nobody names them. Making each departure explicit keeps the necessary complexity and rejects the accidental kind. "Cool" code is not good code; simple code that is still robust and fast is good code.

**How to apply:**
- **Scope discipline:** every addition must trace to a feature the user actually asked for and be necessary for it to function. Building something "while we're here" or "for later" is a KISS failure — that's scope creep. When in doubt whether something is in scope, ask rather than build.
- **Readability is the target:** aim for code a beginner Python programmer could read and understand. Much of this codebase needs advanced features they couldn't — that's allowed, but never done casually. When you reach for an advanced construct, be explicit about *why* the simpler version doesn't work and what it would have cost.
- Before adding a layer, branch, or option, ask: "does this earn its complexity, or is it theater?" (See [[substance-over-theater]].)
- Premature abstraction is a common way to fail KISS — watch for it specifically; the timing call is its own rule, see [[right-sized-abstraction]].
