# Dashboard checks

Browser checks for `aegis dashboard`, run against a throwaway home so nothing touches your real configs.
They need Node and Playwright (`npm i -g playwright`).

```bash
export AEGIS_DEMO_HOME=/tmp/dh            # a scratch HOME with a .claude.json, .cursor/mcp.json and .aegis/
HOME=$AEGIS_DEMO_HOME AEGIS_HOME=$AEGIS_DEMO_HOME/.aegis aegis watch --port 7342 &
URL=$(aegis dashboard --no-open --port 7342 | grep -o 'http[^ ]*')
node scripts/dev/dashboard_e2e.js "$URL"     # clicks every control and checks the files it changed
node scripts/dev/dashboard_audit.js "$URL"   # text size, contrast and overflow on every page, light, dark, phone
```
