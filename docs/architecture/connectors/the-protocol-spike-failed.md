# The Protocol (spike, not implemented)

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### The Protocol connector — spike failed, not implemented

- **Status**: this connector followed a hard two-phase gate — Phase 1 (feasibility spike) before
  any connector code. The spike failed; Phase 2 (`app/connectors/the_protocol.py`, a
  `THE_PROTOCOL` `normalize.py` constant, a `CONNECTOR_REGISTRY` entry) was never started.
  There is no Protocol connector in this codebase. This section exists only to record why, so
  a future attempt doesn't re-spend the investigation from scratch.

- **A materially different obstacle than the other nine connectors' "no JSON endpoint" gap**:
  every plain-HTTP path into theprotocol.it (homepage, a guessed `/api/offers`, its
  robots.txt-listed sitemap) returns `403` with a `cf-mitigated: challenge` header — Cloudflare's
  Managed Challenge, which requires a real JS-executing browser to even attempt, unlike
  Bulldogjob's "no endpoint, but a sitemap + embedded JSON works" situation
  (`docs/adr/0023-bulldogjob-sitemap-and-embedded-next-data-investigation.md`).

- **Why Playwright doesn't work here either** (spiked 2026-07-14, see
  `docs/adr/0024-the-protocol-playwright-cloudflare-feasibility-spike.md` for the full trail): a
  stock headless Playwright Chromium session's *first* navigation to
  `https://theprotocol.it/` reached real content (`200`, real title, real body text) — but every
  navigation after that, across several minutes of normal pacing (not a rapid burst), hit a
  persistent Managed Challenge (`403`, `cf-mitigated: challenge`, title `"Just a moment..."`,
  empty body) that never self-cleared, even after waiting in place on the challenge page. This
  reads as Cloudflare escalating its classification of the client after the first visit
  (automation fingerprinting inherent to a stock headless session), not a simple request-rate
  throttle a rate-limit delay could work around. Headed mode — a suggested fallback — could not
  even be evaluated in the sandbox this spike ran in (`chromium.launch(headless=False)`
  hung trying to reach a display/D-Bus session that wasn't actually available), so it remains
  untested, not confirmed-working.

- **No stealth or CAPTCHA-solving tooling was used or considered** — out of scope by design, and
  using one to force a pass would count as a fail for this spike's purposes regardless of outcome.

- **Revisit conditions**: re-run the Phase 1 spike (same method — one fresh Playwright
  navigation, then repeated navigations over realistic elapsed time, checking `cf-mitigated`
  header / page title / body text) if theprotocol.it's Cloudflare edge configuration changes, or
  if a legitimate non-browser API access path turns up. Until then, The Protocol is not one of
  recruFlow's connectors — `CONNECTOR_REGISTRY` has no entry for it, and `playwright` is not a
  dependency of this repository.
