---
name: deploy-safely
description: "ALIAS - renamed to dev-deploy-safely. Forwards to `dev-deploy-safely`. Kept so `/deploy-safely` and older references still resolve. Triggers on: deploy-safely, deploy safely, safe deploy, deploy gates, pre-deploy checks."
---

# Deploy Safely -> renamed to Dev Deploy Safely

This skill was renamed to **`dev-deploy-safely`**.

**Do this now:** invoke the **`dev-deploy-safely`** skill with the exact same request the caller gave you, and follow it end to end.

`/deploy-safely <args>` is equivalent to `/dev-deploy-safely <args>`. This alias exists only for back-compatibility. New work should call `dev-deploy-safely` directly.
