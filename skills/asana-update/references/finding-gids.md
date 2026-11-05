# Finding the gids you need

Asana names everything by a numeric gid. Read each one from a source; never
type one from memory.

| You need | Where to find it |
|---|---|
| A task gid | The task URL: `https://app.asana.com/0/<project>/<task>` or `.../task/<task>`. The scripts take the URL as it is. |
| A project gid | The project URL: `https://app.asana.com/0/<project>/list`. |
| Your workspace gid | `GET /users/me?opt_fields=workspaces.name` lists your workspaces. |
| Your user gid | `GET /users/me?opt_fields=gid,name`. |
| Another person's gid | `_asana.resolve_user_gid("<email>", token)`, or `GET /workspaces/<ws>/users?opt_fields=email,name`. |
| A section gid | `GET /projects/<project>/sections`. |
| A custom field and its option gids | `GET /projects/<project>/custom_field_settings?opt_fields=custom_field.name,custom_field.enum_options.name`. |
| A story (comment) gid | The `Posted story <gid>` line from `post_comment.py`, or `read_task.py <task> --json`. |

A quick read with the token the scripts use:

```python
import sys
sys.path.insert(0, "scripts")
import _asana

token = _asana.fetch_token()
me = _asana.request("GET", "/users/me", token,
                    params={"opt_fields": "gid,name,workspaces.name"})["data"]
print(me["gid"], me["name"])
for ws in me["workspaces"]:
    print(ws["gid"], ws["name"])
```

Put the values you use often in `~/.claude/asana-update.config.json`:
`workspace_gid`, `user_gid`, and `default_sections` for the boards you create
tasks on.
