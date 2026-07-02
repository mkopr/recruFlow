---
name: jobs-create-profile
description: Turn a plain-language self-description (or pasted CV) into a stored candidate profile, and manage existing profiles. Use when the user says "set up my profile", "here's my CV", "update my preferences", "what's in my profile", or "switch profile". The saved profile is what /jobs-evaluate and /jobs-digest score offers against.
---

# jobs-create-profile

Capture who the user is and what they want, store it as a profile in the database,
and switch between profiles. Profiles are the input to `/jobs-evaluate` and
`/jobs-digest` — every offer is graded against the active profile.

Resolve `sjctl` in this order: (1) on `PATH`, (2) `~/.solid-jobs-skills/bin/sjctl[.exe]`, (3) `./sjctl[.exe]` in the repo. If none exist, install it and use the printed path:
- macOS/Linux: `curl -fsSL https://raw.githubusercontent.com/solid-company/solid-jobs-skills/v0.3.0/scripts/install-sjctl.sh | bash`
- Windows: `irm https://raw.githubusercontent.com/solid-company/solid-jobs-skills/v0.3.0/scripts/install-sjctl.ps1 | iex`
- Dev fallback (Go, inside repo): `go run ./cmd/sjctl`

Profiles live in the database (the `profiles` table), not in a file — these
commands are the only thing that reads or writes them.

## What a profile contains

Fill these fields — they map one-to-one onto the dimensions `/jobs-evaluate`
scores, so the more concrete they are, the better the grades:

- **Role & seniority** — target roles, seniority, years of experience.
- **Skills** — strong, working, learning/willing.
- **Compensation** — minimum acceptable (monthly, gross), target, contract
  preference (B2B / employment / either).
- **Location & work mode** — base city, remote/hybrid/onsite, relocation.
- **Languages**.
- **Deal-breakers** — hard caps (e.g. below minimum salary, onsite-only). These
  cap an offer's grade in `/jobs-evaluate`, so be explicit.
- **Nice-to-haves**.

The layout to follow is `config/profile.md` in the repo — match its headings.

## Create or update a profile from natural language

1. Gather the fields above from what the user wrote (or pasted CV text). Ask only
   for the missing essentials — at minimum role, seniority, minimum salary, work
   mode, and any deal-breakers.
2. Write the filled markdown to a **temp file** (e.g. the OS temp dir).
3. Save it:
   - New profile: `sjctl profile add <name> --file <tempfile>` (add `--default` if
     it's their first/main profile).
   - Existing profile (replace its content): `sjctl profile import <name> <tempfile>`.
   Check `sjctl profile list --json` first to decide which.
4. Delete the temp file.
5. Show the user a short summary of what was saved and which profile is now default.

## Manage profiles

| Intent | Command |
|--------|---------|
| List profiles (default marked) | `sjctl profile list --json` |
| Show one profile's content | `sjctl profile show [name] --json` |
| Switch the active profile | `sjctl profile set-default <name>` |

Multiple profiles are useful for trying different strategies (e.g. "backend-remote"
vs "anything-that-pays"); `/jobs-evaluate` and `/jobs-digest` use the default unless
called with `--profile <name>`.

## After saving

Tell the user the profile is live: `/jobs-evaluate` will grade offers against it,
and `/jobs-digest` will rank new offers by it. Suggest running a `/jobs-search` and
then evaluating a result to see the profile in action.
