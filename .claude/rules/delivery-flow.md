# Delivery flow: atomic commits, PR to the integration branch, verified, merged, cleaned up

**Rule:** A task is done when it is merged and its issues are updated, not when the code compiles. The flow for every task:

1. Work on a feature branch (in a git worktree when several tasks run in parallel), branched from the integration branch: `develop` if the repo has one, otherwise `main`.
2. Commit atomically: one verified, logical change per commit, each commit builds and passes the suite. Commit each verified step as you go (see [[verify-before-moving-on]]), never one batch at the end of a session.
3. Run the project's formatter, linter, type checker, and tests before pushing (see [[tooling-and-types]]).
4. Push and open a PR targeting the integration branch. Reference the issues it covers.
5. If CI exists, wait for it to be green and fix failures before merging. A PR that conflicts with its base gets no CI at all: rebase onto the base, re-run the suite, `push --force-with-lease`.
6. Merge.
7. Report back on the related issues: close the ones the work fully resolves; comment on the ones with work left. Never close an issue with work still in it.
8. Clean up: delete the merged branch locally and on `origin`, and remove the worktree. Verify only your own branch went; never touch another session's worktree.

**Never target `main` directly when a `develop` branch exists.** `main` is production; promotion `develop` to `main` is a human-opened, human-approved PR. Never delete `develop` or `main`.

**Why:** Leftover branches and worktrees make it impossible to see what is actually in flight. Small commits keep parallel-worktree history mergeable and show how far the work really got. Merging to production is the one step an automated agent must not be the one to take, and where branch protection is missing, discipline is the only guard.

**How to apply:**
- Conventional, descriptive commit messages. The commit message is where "why this change" lives, not a code comment (see [[clean-artifacts]]).
- **Never run `git checkout -- <file>` or `git restore <file>` to undo one tweak.** It discards every uncommitted edit in that file. Apply a targeted inverse edit, or make a WIP commit before experimenting.
- **Never delete `.git/index.lock` in a retry loop.** Wait for it to clear (poll up to ~30 s); only remove a lock that is verifiably stale (no git process running and an old mtime). Deleting a live lock can zero the index.
- Verify a merge or rebase actually landed (`git log -1`, or check a file the branch adds) rather than trusting the exit message.
- When other sessions work the same repo, `git fetch` and check the base branch and open PRs before each step of a multi-step plan; a plan pushed to the integration branch is a work queue others pick from.
- When stacking dependent work, branch the child off the parent PR's branch and open its PR only after the parent merges. Always check that a PR is actually merged before deleting its branch.
- Secrets, generated output, and personal data never enter a commit; see [[security-and-secrets]]. Update `.gitignore` when new generated folders appear.
