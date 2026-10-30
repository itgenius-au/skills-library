# Step 8: close this session's browser tabs (pick up / done)

Steps:

1. If the extension tab tools are not loaded, load them: `ToolSearch "select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_close_mcp"`. If that returns no such tools, skip this step.
2. Read this session's group **without creating one**: call `tabs_context_mcp` with no arguments (do NOT pass `createIfEmpty`). "No tab group exists for this session" means nothing to clean - stop here.
3. For each tab id returned, call `tabs_close_mcp`. Closing the last tab auto-removes the group.
4. Report which tabs closed (title / url) in one line.

Guardrails:

- **Never pass `createIfEmpty`** here: that would spawn a fresh group, the opposite of cleanup.
- If the user asked to keep a tab open (a page for them to read), skip that tab.
- This cleans only the **current** session's group. It cannot close groups orphaned by earlier sessions (the binding is already lost); those need a manual right-click, then Close group.
