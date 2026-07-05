# recruFlow

Local job-application automation system. This file extends `CLAUDE.md`'s domain glossary table with terms resolved during design/grilling sessions — precise definitions and the alternatives deliberately rejected, not implementation detail.

## Language

**Grade Scale**:
The object that converts a Matcher's weighted dimension total into a letter grade (A–F), via a `grade_for(weighted_total)` method paired with the threshold data it applies. Introduced in P3US22 as a seam — a scoring engine takes a `GradeScale` instance rather than reading a hardcoded threshold constant directly — so a later story (P3US27) can supply one built from persisted, user-editable cutoffs without the engine code knowing persistence exists.
_Avoid_: Grade thresholds (the raw data alone, not the behavior), grading config

**Scoring Configuration**:
The single global, Profile-independent record of the four cutoff values a `Grade Scale` is built from. Deliberately not a field on `Profile`: thresholds calibrate what a letter grade *means*, so switching the active Profile must never silently change what "B" means. One row, always — no activation flag, unlike Profile's one-active-of-many pattern.
_Avoid_: Grading preferences, profile thresholds

**Deal-Breaker Cap**:
The rule that any Profile deal-breaker matched in an Offer caps the Matcher's grade at D, regardless of the weighted dimension total. Enforced in code after the LLM call (a deterministic backstop), never left to the LLM to self-apply — a future engine (or a prompt-only implementation) that skips this code-level check would be non-compliant even if the model's rationale mentions the deal-breaker. **Detection itself is also deterministic, never an LLM-judged field** — see `docs/adr/0014-deal-breaker-detection-deterministic-not-llm.md`: offer text is adversarial, so folding detection into the LLM's structured output would let a manipulated listing talk the model out of flagging a real deal-breaker. Matching is case-insensitive and tokenizes on hyphen/underscore/slash/whitespace, joining tokens with an *optional* separator (`"on-site"` / `"onsite"` / `"on site"` all match one pattern) while single-token deal-breakers keep plain word boundaries (so `"Java"` never matches inside `"JavaScript"`) — a deliberate recall-vs-security trade-off: paraphrased deal-breakers ("must work from the office" vs. a `"remote-only"` deal-breaker) are missed, in exchange for a guarantee that cannot be prompt-injected around.
_Avoid_: Red flag penalty (red flags are one of the six weighted dimensions at 5%; the deal-breaker cap is a separate, absolute override on top of the weighted total, not part of that dimension's score)
