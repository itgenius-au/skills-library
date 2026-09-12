# Query recipes

Run these against your own vault. Replace `PROJECT` with your `bq_project` and `DS` with your
dataset (default `claude_memory_vault`). From the shell, prefix with the isolated config so you
query as the vault SA:

```
CLOUDSDK_CONFIG=~/.config/gcloud-vault bq query --nouse_legacy_sql '<SQL>'
```

**Recent sessions**

```sql
SELECT session_id, MIN(timestamp) AS started, MAX(timestamp) AS last, COUNT(*) AS rows
FROM `PROJECT.DS.messages`
GROUP BY session_id
ORDER BY last DESC
LIMIT 20;
```

**Search content**

```sql
SELECT timestamp, role, machine, SUBSTR(content, 0, 200) AS snippet
FROM `PROJECT.DS.messages`
WHERE content LIKE '%stripe webhook%'
ORDER BY timestamp DESC
LIMIT 50;
```

**Models used per session**

```sql
SELECT session_id, model, COUNT(*) AS rows
FROM `PROJECT.DS.messages`
WHERE model IS NOT NULL
GROUP BY session_id, model
ORDER BY session_id;
```

**Activity by machine (last 7 days)**

```sql
SELECT machine, COUNT(DISTINCT session_id) AS sessions, COUNT(*) AS rows
FROM `PROJECT.DS.messages`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY machine
ORDER BY rows DESC;
```

**Token usage per day**

```sql
SELECT DATE(timestamp) AS day,
       SUM(input_tokens)  AS input_tokens,
       SUM(output_tokens) AS output_tokens
FROM `PROJECT.DS.messages`
WHERE output_tokens IS NOT NULL
GROUP BY day
ORDER BY day DESC
LIMIT 30;
```

**Currently-live sessions (needs `heartbeat_enabled`)**

```sql
SELECT session_id, machine, project_dir, git_branch, MAX(last_active) AS last_active
FROM `PROJECT.DS.session_heartbeat`
GROUP BY session_id, machine, project_dir, git_branch
HAVING last_active > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 MINUTE)
ORDER BY last_active DESC;
```
