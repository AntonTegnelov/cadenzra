# Fix bugs test-first; pin the contract, not the instance

**Rule:** When fixing a bug, first write a test that fails *because of the bug*. Make the minimum change needed to pass it. Then run the surrounding suite to confirm you broke nothing else. This is the debugging discipline — not full TDD for every new feature.

**Why:** A test written after the fix proves nothing about the fix; you can't tell it would have caught the bug. Writing it first, watching it fail for the right reason, then watching it pass, is the proof. And a bug is rarely a one-off typo — it's a violated contract or a false assumption that the same mind will make again in a sibling code path. A test pinned to the specific reproduction guards one input; a test pinned to the *contract* guards the whole class of mistake.

**How to apply:**
- Write the failing test first and confirm it fails for the reason you expect — not a setup error, not an unrelated assertion. A test that passes before the fix is testing the wrong thing.
- Phrase the assertion around the **invariant or contract that was breached**, not the literal values in this report. Ask: "if I (or someone else) re-make this same thinking mistake elsewhere, does this test trip?" If only this exact input would trip it, generalize it.
- Make the minimal change that satisfies the test. Resist fixing adjacent things in the same pass — note them and handle them as their own tasks (see [[verify-before-moving-on]]).
- Run the local suite around the change before moving on. The point of "test-first" is wasted if you don't confirm the fix is regression-free.
- If the bug was a broken internal invariant, the right long-term guard is often to make that invariant fail loudly at its source rather than only in a test — see [[fail-loud]].
