# Superseded Cloud Hit Snapshot

This tracked snapshot is retained only to prevent stale operational claims. It is not current cloud evidence and must not be used for production, model, or PEA-CON claims.

Use `runtime/production_cloud_real_hit_check.ps1` with authenticated GET-only access instead. The current guard writes JSON and Markdown reports under `runtime/private/`, emits only redacted hash references, and requires `production_send=blocked`.

The public console is demo-isolated and is not an evidence source.
