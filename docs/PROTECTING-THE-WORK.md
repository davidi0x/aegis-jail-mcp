# Protecting the work (and why the code stays open)

A common instinct is to hide or obfuscate the source so competitors can't copy
the innovation. For Aegis that would be both impossible and self-defeating, so
here is the honest strategy instead.

## Why we don't obfuscate
- **It's already published.** The source *is* the distribution. You cannot
  "reverse engineer" what is printed in full on GitHub.
- **Obfuscated Python is not protection.** It decompiles in minutes; it only
  annoys honest readers.
- **A black-box security tool is worthless.** Nobody gives their terminal,
  credentials and repositories to a sandbox they cannot audit. Auditability *is*
  the product. Hiding the code would destroy trust and adoption — the opposite of
  the goal.

## What actually gives us exclusivity

1. **Copyleft license (AGPL-3.0).** Anyone may use and fork Aegis, but if they
   build on it — including running a *modified* version as a network service —
   they must release their changes under the same license (AGPL §13, "the
   network-use clause"). A competitor cannot take Aegis, improve it privately and
   ship a closed product. They either contribute back or build their own.

2. **Trademark.** The name "Aegis" and the logo are not licensed by the AGPL.
   A fork must rename. "Aegis" keeps meaning *this* audited project. See
   TRADEMARK.md.

3. **Open core.** The free, open part is the engine: the sandbox, probes,
   optimizer, MCP jail, scanner. The parts a *team or company* pays for — central
   policy management, org-wide audit dashboard, SSO, long-term audit storage,
   support and signed enterprise builds — are a separate, hosted service whose
   server code is not published. Competitors can copy the engine (and must share
   improvements); they do not get our hosted product, our brand or our users.

4. **Be the reference implementation.** Own the canonical repo, the PyPI name,
   signed releases and provenance. The threat model, the CI matrix and the test
   suite are the moat: matching them is most of the work, and they keep moving.

## What this means in practice
- Keep every security-relevant line open and auditable.
- Keep the paid/hosted differentiators as a separate private service, never in
  this repository.
- Enforce the trademark on names and logos, not on the code.
