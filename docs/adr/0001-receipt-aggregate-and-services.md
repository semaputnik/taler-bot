---
status: accepted
date: 2026-10-16
---

# Receipt is an aggregate; services orchestrate, the domain holds the rules

A receipt is stored across six tables (receipts, receipt_photos, receipt_parses,
receipt_items, receipt_issues, receipt_edits) that must change together: the header is
the current parse with the user's edits applied, items are rebuilt whenever the current
parse changes, a merged receipt points at its target. Five user actions (parse, refine
with another photo, undo, edit an item, merge) each have to restore that consistency.

We decided to model `Receipt` as an **aggregate** in `src/domain`: a class whose
methods (`apply_parse`, `undo_to`, `record_edit`, `merge_into`, …) own those rules, with
photos, parses, items, issues and edits as its private parts. `ReceiptRepository` loads
and saves the whole aggregate, one repository per aggregate, not per table. `Store` and
`StoreProduct` form a second aggregate (`Catalog`): they outlive receipts and are edited
by hand. `src/services` are application services: they load aggregates, call the LLM
outside any transaction, call one aggregate method, save and commit. They contain no
receipt rules. Stateless logic that fits no entity (normalizing raw LLM output, finding
a near-match among several receipts) lives in `src/domain` as domain services.

This follows Percival & Gregory, *Architecture Patterns with Python*
(https://www.cosmicpython.com/book/), chapters 1, 4 and 7, which is the reference for
architecture discussions in this project.

## Considered options

- **Table-per-repository + rules in services** (what tickets #5–#6 built): every action
  orchestrates 5–7 repositories and repeats the same rebuild logic. Forgetting one step
  in one action leaves a receipt inconsistent. Rejected as an anemic domain model.
- **Table-per-repository + rules in `domain` as free functions** (`normalize`,
  `apply_edits`, `diff`): the rules are pure and testable, but detached from the data
  they protect, and callers can still skip them. Rejected as a utils bag.
- **Use cases (one class per action) instead of services**: tried first; dropped for the
  paper-work-bot shape of one service class per entity with action methods, which the
  user prefers. The aggregate decision is independent of this choice.

## Consequences

- The per-table repositories for receipt parts written in #5 and #6 are replaced by
  `ReceiptRepository`; their constraint tests move to the aggregate repository.
- The ORM ↔ aggregate mapping lives in `src/database`; `domain` stays free of SQLAlchemy.
- Domain rules are unit-tested on `Receipt` objects without Postgres; the repository is
  tested as "save, load, same aggregate".
- The DB CHECK/unique constraints stay as a second line of defence; the aggregate is the
  first.
