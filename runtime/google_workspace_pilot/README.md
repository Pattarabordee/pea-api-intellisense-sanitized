# Superseded Google Workspace Pilot

This directory is retained as historical source only. Do not deploy, redeploy, test against, or send AIS traffic to this Google Apps Script pilot.

The approved receiver is the authenticated Render Go API. It requires `X-API-Key` or Bearer authentication, keeps `mode=shadow`, `production_send=blocked`, and `CALLBACK_TRANSPORT=dry_run`.

The legacy pilot used a query/body key and did not provide the strict HTTP/authentication boundary required by the current architecture. It is excluded from the sanitized source bundle and from production/PEA-CON evidence.

An owner who controls any historic Apps Script deployment must separately disable or archive it. This repository change does not call Google Apps Script or alter any external deployment.
