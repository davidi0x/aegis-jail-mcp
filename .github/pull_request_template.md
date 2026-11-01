## What does this change?

## Why?

## Checklist
- [ ] Tests added or updated (sandbox changes need a test that runs against the real OS sandbox)
- [ ] `AEGIS_REQUIRE_SANDBOX=1 python3 -m unittest discover -s tests -t .` passes
- [ ] No new runtime dependencies
- [ ] If this changes a defence, `docs/THREAT_MODEL.md` is updated
- [ ] If this changes output shown in the README, `python3 scripts/make_images.py` was re-run
