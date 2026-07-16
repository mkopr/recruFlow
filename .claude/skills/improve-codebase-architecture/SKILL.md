---
name: improve-codebase-architecture
description: Scan a codebase for deepening opportunities, write each one up as a BUG file in `user stories/BUG/`, then grill through whichever one you pick.
disable-model-invocation: true
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities** — refactors that turn shallow modules into deep ones. The aim is testability and AI-navigability.

This command is _informed_ by the project's domain model and built on a shared design vocabulary:

- Run the `/codebase-design` skill for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly in every suggestion — don't drift into "component," "service," "API," or "boundary."
- The domain language in `CONTEXT.md` gives names to good seams; ADRs in `docs/adr/` record decisions this command should not re-litigate.

## Process

### 1. Explore

Read the project's domain glossary (`CONTEXT.md`) and any ADRs in the area you're touching first.

Then use the Agent tool with `subagent_type=Explore` to walk the codebase. Don't follow rigid heuristics — explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow** — interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? A "yes, concentrates" is the signal you want.

### 2. Write each candidate as a BUG file

Each deepening opportunity becomes its own file in `user stories/BUG/`, following the exact convention already used by `BUG01`–`BUG10` in that directory — read a couple of the existing files first to match tone and structure before writing new ones.

**Numbering**: `ls user stories/BUG/` to find the highest existing `BUG<NN>`, then continue the sequence (zero-padded to 2 digits). Don't reuse or renumber existing files.

**Filename**: `user stories/BUG/BUG<NN>_<short_snake_case_slug>.md` — the slug names the finding, not a category (e.g. `BUG11_ingestion_dispatch_duplicated_across_three_connectors.md`).

**Template** (mirror this section order exactly):

```markdown
# BUG<NN> · <one-line summary — specific, names the actual symptom/finding>

## Summary

What you found and why it matters — in terms of the **codebase-design** vocabulary (shallow module,
seam, locality, leverage, the deletion test) and the **CONTEXT.md** domain terms for anything
domain-specific. State plainly what triggered the finding (e.g. reading X while exploring Y).

## Where It Shows Up

- `path/to/file.py:12-34` — one line per location, exact and citable
- `path/to/other_file.py:5` — no vague pointers, every line must be checkable

## Problem

Plain English: why the current shape causes friction. Apply the deletion test explicitly if it
supports the case ("deleting this concentrates complexity in X rather than removing it, because...").

## Suggested Fix

1. Numbered, concrete steps describing what would change — plain English, not code.
2. Include test/fixture implications if the deepening changes what's testable through the interface.

## Wins

- Terse bullets, concrete, tied to locality/leverage/testability — not generic praise

## Related

- Other `user stories/` files, ADRs, or source files this touches or depends on
```

Also include, directly under the title, a one-line strength marker:

`**Recommendation:** Strong` / `Worth exploring` / `Speculative`

**ADR conflicts**: if a candidate contradicts an existing ADR, only write it up when the friction is real enough to warrant revisiting the ADR. Add a line under the recommendation marker: `**Conflicts with:** ADR-0007 — but worth reopening because...`. Don't write up a BUG file for every theoretical refactor an ADR forbids.

**Use CONTEXT.md vocabulary for the domain, and the `/codebase-design` vocabulary for the architecture.** If `CONTEXT.md` defines "Order," talk about "the Order intake module" — not "the FooBarHandler," and not "the Order service."

Do NOT propose interfaces yet — the BUG file describes the problem and a suggested fix, not a finished design.

Once all candidates are written, list them for the user (number, one-line title, recommendation strength) and name which one you'd tackle first and why. Ask: "Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, run the `/grilling` skill to walk the design tree with them — constraints, dependencies, the shape of the deepened module, what sits behind the seam, what tests survive.

Side effects happen inline as decisions crystallize — run the `/domain-modeling` skill to keep the domain model current as you go:

- **Naming a deepened module after a concept not in `CONTEXT.md`?** Add the term to `CONTEXT.md`. Create the file lazily if it doesn't exist.
- **Sharpening a fuzzy term during the conversation?** Update `CONTEXT.md` right there.
- **User rejects the candidate with a load-bearing reason?** Offer an ADR, framed as: _"Want me to record this as an ADR so future architecture reviews don't re-suggest it?"_ Only offer when the reason would actually be needed by a future explorer to avoid re-suggesting the same thing — skip ephemeral reasons ("not worth it right now") and self-evident ones. Note the ADR reference back in the BUG file's `## Related` section.
- **Want to explore alternative interfaces for the deepened module?** Run the `/codebase-design` skill and use its design-it-twice parallel sub-agent pattern.
- **Fix gets implemented in this session?** Rename the BUG file to append ` DONE` before the `.md` extension, matching the existing convention (e.g. `BUG06_force_refresh_silently_ignored_by_two_connectors DONE.md`).
