# Code, comments, docs, and copy stand on their own

**Rule:** Every artifact (source, comments, docstrings, design docs, README, user-facing copy) must read cleanly to a future reader who has no access to the conversation, task, or history that produced it. Write the new state; never describe the change.

**Why:** Artifacts outlive the chat. "As discussed above", "updated to reflect the new requirements", "previously this said X", "added per request", "fixes issue #123 by..." make no sense to the next reader and rot immediately. Copy that reads as machine-generated undermines trust in anything it describes.

**How to apply:**

### Comments and docstrings
- Comment the *why* of non-obvious code, not the *what*. If a comment restates the line below it, delete it.
- No comments that reference the task, fix, PR, ticket, or conversation that introduced the change. That belongs in the commit message and PR description.
- Do not add docstrings or comments to code you did not change. Drive-by documentation churn hides the real diff.
- Document public API surfaces (purpose, parameters, return, errors, panics) in the language's doc-comment convention; keep internals lean.
- No dead code, no commented-out code, no `TODO` without an owner or issue reference.

### Docs
- Design docs under `docs/` are authoritative for the behaviour they describe. Read the relevant one before changing that behaviour. When implementation corrects a doc, update the doc in the same change and say so inline, pointing at the evidence; don't leave the doc lying.
- A doc is not a changelog unless it is explicitly the changelog. Refer to a previous version only when it is genuinely required to understand the current state (a migration guide, a breaking change).
- Delete done items from TODO files rather than archiving them; the TODO is a queue, not a history.

### Prose and copy (docs, READMEs, UI text, site copy, commit bodies)
- No em dashes. Use commas, colons, parentheses, or a new sentence. Rewrite the sentence rather than just swapping the dash for a hyphen.
- No LLM-sounding phrasing: no "delve", no "X — Y" title patterns, no middle-dot lists, no fragment-list sentences, no "seamlessly", no closing summaries that restate the paragraph. Plain, complete sentences.
- Match the existing voice and conventions of the document you are editing; leave the owner's own pre-existing copy alone unless asked.
- Keep names, numbers, and claims exactly as the source material states them; never invent facts to fill a template.
