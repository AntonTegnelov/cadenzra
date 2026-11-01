# UIs, CLIs, and API handlers are thin renderers over the domain

**Rule:** Any surface a user or agent drives (a GUI, a CLI, a web frontend, an HTTP/GraphQL resolver) is a dumb renderer over the domain package. Real logic (loops, scheduling, orchestration, retry policy, state transitions, derived state) lives in the domain, exposed through one entry point that every surface calls. A surface's job is to assemble options, invoke one method, and render what comes back.

**Why:** There is exactly one flow engine. Duplicating logic across two surfaces is how they drift apart, and a client-side state machine that shadows the server's produces two sources of truth. Keeping surfaces thin means a behaviour change is a domain change, not a multi-surface coordination. It also makes every capability observable from the CLI, which is the only surface an agent can actually see.

**How to apply:**
- When a feature is requested, don't ask *which* surface it lives on. Build it in the domain, define the seam in the interfaces package if several surfaces bind to it (see [[protocol-boundaries]]), wire it in the composition root, and let each surface be a few lines over the top.
- A loop in a CLI command, a timer in a GUI tab, an `if user has answered X and not Y` in React: each is a sign the logic is on the wrong side.
- Frontends render what the backend returns. Expect a discriminated union or a typed state object; switch on its tag and render. Mutations return the new state; don't reconstruct it client-side.
- If you want to compute "is this done?" or "what's next?" in a surface, add that field to the domain's returned type instead.
- Local surface state is limited to ephemeral UI concerns (focus, drafts being typed, open/closed). Anything that persists across a navigation or reload belongs in the domain or on the server.
- Where both a GUI and a CLI exist, they are equal: a capability is not finished until both can drive it. Extra read/inspect commands on the CLI are not an asymmetry; printing is its comparative advantage.
- Presentation belongs to the presentation layer: templates own visual decisions (colours, fonts, spacing); the code passes data, never styling.
