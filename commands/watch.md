---
description: Check whether Aegis Autopilot is running and how it is set up
---

Call the `aegis_watch_status` MCP tool and tell the user, in a few lines:
whether Autopilot is running, the dashboard address if it is, how many events are open and which settings are on (auto-jail, notifications, responder).
If it is not running, give the one command to start it as a background service: `aegis watch install`.
Do not change settings unless the user asks.
