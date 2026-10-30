# Phase 3: naming check and cloud location check

- **Naming check (immutable names only; escalate only on a miss).** Phase 2
  surfaced where the code lives and what precedents exist. Before writing code,
  check every NEW name this build introduces that cannot be renamed in place, where
  a rename means delete-and-recreate or a data migration: a deployed service,
  service account, storage bucket, secret, data-warehouse dataset and table, database,
  table and column names, etc. Check infra names against your project's naming
  conventions and schema names against its existing patterns. Mutable names (files,
  modules, the branch, functions, UI components, routes) never pause the build: follow
  the project's existing patterns and go on. An immutable name that conforms proceeds
  silently - this stays the no-pause fast path. But a name that does NOT conform, or
  has no precedent to follow, is a genuine design decision: STOP and escalate it to the
  user for a naming call before Phase 4 (the same escalation this phase already makes
  for a design/trust decision). Ask in chat: show each candidate name as exact text in
  a code span and take the reply in chat. Do NOT put a name choice in a multiple-choice
  question pop-up: its short option labels make the agent shorten or rewrite names, so
  the exact spelling is lost. Record the chosen names in the runbook Decisions section.
- **Cloud location check (same rule: escalate only on a miss).** For every NEW cloud
  resource with a region or location (a deployed service, database instance, data-warehouse
  dataset, storage bucket, registry repository), write its location in the runbook beside
  its name and check it against your project's location rules (in short: co-locate with the
  resources it talks to, measured live with your cloud CLI; a regional service never takes a
  multi-region location). A conforming location proceeds silently. Any other location is a
  design decision: STOP and escalate it in chat with its reason, before Phase 4.
  A location cannot change after create. Pass it explicitly (`--region` /
  `--location`) on every create command; never let a tool's default decide.
