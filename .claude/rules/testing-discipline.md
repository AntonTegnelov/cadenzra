# Tests: integration over mocks, contracts over internals, never against live third parties

**Rule:** Prefer integration tests that exercise real component interactions over unit tests built on mocks. Mock only at the interface boundaries of [[protocol-boundaries]] (a vendor, a binary, the network), never concrete internal types. Tests assert behaviour and contracts, not implementation details. Tests, CI, and dev tooling never touch a production surface or a live third-party service.

**Why:** A test that breaks on a refactor without a behavioural change is a liability, and a mock-heavy suite mostly tests the mocks. Real interactions catch the bugs that matter: wiring, serialization, ordering, state. Live third-party traffic from tests is a ban risk, a cost, and a flakiness source; production surfaces (real alert channels, real user data, real accounts) must stay all-signal.

**How to apply:**
- **Structure:** Arrange, Act, Assert, separated by blank lines. One behaviour per test; if a test needs to verify two independent behaviours, write two tests. Name the test for the contract it pins (`given_x_when_y_then_z` or a plain sentence).
- **Test through public interfaces.** Don't reach into private functions; if a private function needs its own test, that's usually a sign it wants to be a public unit of its own module. Never weaken encapsulation for testability.
- **Fakes over mocks.** For I/O (databases, HTTP clients, object stores) use in-memory fakes or transaction-rollback patterns rather than mocking every method call. Hand them in through the composition root; no monkeypatching of internals.
- **Never skip on a missing prerequisite.** If a test needs a fixture, a key, or a binary and it is absent, the test fails and says why. Silent skips hide broken environments. Marker-based opt-in suites (e.g. `local_only`, `integration`) are the sanctioned way to separate tests that need real resources, and CI runs everything else.
- **Offline by default.** Selector/extraction/parsing tests run against saved fixtures committed under `tests/`. When new work needs fresh real-world data, capture it once by hand into fixtures; don't hit the live site from the suite.
- **Test channels are separate from production channels.** Dev and smoke runs use the test webhook, the test project, the test bucket. A production endpoint is used only by actual product runs, never by "just checking it works".
- **Fixtures carry no real personal data.** Sanitized stand-ins only (see [[security-and-secrets]]).
- **Run the relevant suite before calling a task done**, and the full suite plus linters before opening a PR (see [[delivery-flow]]).
- Coverage is a signal, not a target. Test edge cases, error paths, and boundary conditions because they are where bugs live, not to move a number.
- How and when to write a test for a bug fix is in [[tdd-mindset]].
