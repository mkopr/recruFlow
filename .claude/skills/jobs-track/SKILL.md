---
name: jobs-track
description: Manage the job application pipeline — add offers, move them through statuses (saved/applied/interview/offer/rejected), add notes, and view the board. Use when the user wants to track applications or check pipeline status.
---

# jobs-track

Manage the application pipeline via `sjctl track`.

Resolve `sjctl` in this order: (1) on `PATH`, (2) `~/.solid-jobs-skills/bin/sjctl[.exe]`, (3) `./sjctl[.exe]` in the repo. If none exist, install it and use the printed path:
- macOS/Linux: `curl -fsSL https://raw.githubusercontent.com/solid-company/solid-jobs-skills/v0.3.0/scripts/install-sjctl.sh | bash`
- Windows: `irm https://raw.githubusercontent.com/solid-company/solid-jobs-skills/v0.3.0/scripts/install-sjctl.ps1 | iex`
- Dev fallback (Go, inside repo): `go run ./cmd/sjctl`

## Pipeline

```
saved → applied → interview → offer
                            ↘ rejected
(any) → expired   (set automatically when the offer's validTo passes)
```

## Commands

| Intent | Command |
|--------|---------|
| Start tracking an offer | `sjctl track add <offerKey>` |
| Show the board | `sjctl track list --json` |
| Filter by stage | `sjctl track list --status applied --json` |
| Move stage | `sjctl track set <offerKey> interview` |
| Add a note | `sjctl track note <offerKey> "recruiter call Tue 3pm"` |
| Stop tracking | `sjctl track rm <offerKey>` |

The offer must be cached (seen by a prior search) before it can be tracked.
All commands act on the default profile unless `--profile <name>` is given.

## Flow

1. For "track this" / "I applied", resolve the offer key and run the matching command.
2. For "where am I" / "show my pipeline", run `track list --json`, then group by
   status and present a compact board as a **markdown table** with a clickable
   title. Each tracked row carries a `url`; make the title link to it:

   | Offer | Company | Status | Grade | Key |
   |-------|---------|--------|-------|-----|
   | [Senior Go Engineer](https://solid.jobs/…) | Acme | applied | B | `abc123` |

   The grade column comes from the latest evaluation; fall back to the plain title
   if `url` is empty.
3. `list` auto-expires stale offers first, so the board always reflects which offers are still open.

## Notes

- Status names are exact: `saved`, `applied`, `interview`, `offer`, `rejected`, `expired`.
- Terminal states `offer` and `rejected` are never auto-expired.
