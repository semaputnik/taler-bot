---
status: accepted
date: 2026-10-17
supersedes-in-part: ADR-0001
---

# One receipt has one photo and one parse

ADR-0001 modelled a receipt with several photos, a history of parses, refinement from a
second photo, undo, merging of two receipts and near-matching. That machinery existed to
let a user improve a bad reading by sending another photo. We decided to drop it: a bad
reading is fixed by **deleting the receipt and sending a new photo**, or by editing the
values by hand.

A `Receipt` therefore has exactly one `Photo` and at most one `Parse`. `apply_parse` sets
or replaces the parse (the user's edits are kept on top, which is what a re-parse with a
newer `parser_version` needs); there is no parse history, no `undo`, no `merge`, no
`attach_photo`, no near-match, no `receipt_messages` and no `merged` / `awaiting_match`
status. Deletion stays soft (`deleted_at`): the photo and the parse remain for improving
the prompt, and lists never show deleted receipts.

The rest of ADR-0001 stands: `Receipt` and `Catalog` are aggregates with one repository
each, rules live on the aggregate, services orchestrate and hold no rules.

## Considered options

- **Keep multi-photo as built** (iteration 2): it works and is tested, but every receipt
  feature from here on (intake, card, issue review, re-parse, import) would carry the
  cost of photo lists, parse histories and merge semantics for a case the user does not
  want to support. Rejected.
- **Keep the schema, restrict the code**: fewer changes now, but the tables would promise
  what the code refuses, and agents would keep building against the schema. Rejected.

## Consequences

- Schema change: `receipt_photos` and `receipt_parses` become 1:1 with `receipts`
  (unique `receipt_id`); `receipt_messages`, `receipts.merged_into_id` and the
  `merged` / `awaiting_match` statuses are dropped; `receipts.current_parse_id` goes
  (the parse row is found by `receipt_id`).
- The `Receipt` aggregate, `ReceiptRepository`, `ReceiptService` and their tests shrink
  accordingly. `ParseOutcome` stays, reduced to the product keys a re-parse releases.
- The dedupe check on `telegram_file_unique_id` stays: the same photo sent twice is
  answered "already have this photo" without an LLM call.
- `docs/features.md` loses the multi-photo section and the `📷 Add photo` / `↩️ Undo`
  buttons; "Delete" becomes the documented way to redo a receipt.
