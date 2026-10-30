# Phase 5: gate notes

On Node 25 or later, run vitest with jsdom as `NODE_OPTIONS=--no-experimental-webstorage npm test`.
Node's own `localStorage` global hides jsdom's, so every test that touches storage fails with
"Cannot read properties of undefined (reading 'getItem')". A flag on `node` alone does not reach
the vitest workers. Check `node --version` and the CI Node version before you treat a mass storage
failure as your change.

On a shared machine under load (check `uptime`), a full test run can time out tests in areas your
diff never touched. Before you debug them, run a control: run the failing files alone, then run the
same full suite on an unmodified copy of `origin/<default-branch>` on the same machine
(`git archive origin/<default-branch> | tar -x -C <empty tmp dir>`, reusing the installed
dependencies read-only, for example a symlinked `node_modules`). If the default branch times out the
same way, record both results in the runbook and let CI's runner decide. Never raise per-test
timeouts to make a loaded local run pass.

If your change altered anything a machine-checked docs/fact artifact describes (endpoints,
migration/schema head, scheduled jobs, page-access columns, etc.), regenerate that artifact
before running the full suite - a stale one fails a drift test unrelated to your change and
reads as a surprise red instead of an expected step.

**Old values after a rule change.** When the change removes or flips a rule or default (a payment term,
a switch's default), grep the whole repo for the old value before the first review: `docs/`,
`docs/plans/` runbooks, skill text, script `--help` text and test names. Fix each hit or add a
supersede note, and list the hits in the runbook. (Otherwise an adversarial pass keeps finding the
stale text, a different file each round.)

**Mutation testing runs on a copy.** If you run a mutation pass, run it on a plain copy of the
checkpoint with its own virtualenv, never in the build worktree. An in-place pass rewrites source
files, so it cannot overlap the full suite or a review, and a review that reads mutated source reports
false findings.
