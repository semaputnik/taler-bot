# Features and dialogs

Agreed with the user on 2026-10-16, revised on 2026-10-17 (ADR-0002: one photo per
receipt). The MVP scope is not planned yet. Stages describe order
and dependencies, not commitments.

## Decisions

- **Data belongs to the Telegram user** the bot is talking to. Every row is scoped by
  `user_id`. A household or shared view is out of scope for now.
- **The UI is in English.** All texts live in fluentogram `.ftl` files (`en` locale);
  another language is one more locale directory.
- **One photo per receipt** (ADR-0002). A bad reading is fixed by deleting the receipt
  and sending a new photo, or by editing values by hand. The same photo sent twice is
  refused without an LLM call; a second photo of the same receipt (same receipt key) is
  refused too.
- Dropped: price lookup across stores (`/price`) and price-rise alerts. There is no
  canonical-product table.

## Stages

**Stage 0: n8n parity (done).** Photo → save → parse → summary. Covers "not a receipt",
failures, the same photo sent twice and the same receipt photographed twice.

**Stage 1: working with a receipt after parsing**
1. **Receipt card.** Inline buttons under the summary: `Items`, `Photo`, `Delete`
   (`Review` comes with the issue-review spec). Delete is done; Items and Photo follow.
2. **Issue review.** Walk through high/medium issues one at a time. For each, confirm the
   assumed value or enter the right one (date, total, card last 4, lines that don't add up).
3. **Item edit.** Name, category, quantity/price. Name and category are saved to
   `store_products`, so future receipts pick them up.
4. **Receipt history** `/receipts`. Paginated, filtered by month and store; a row opens
   the card.
5. **Reparse.** One receipt by hand, or in bulk for `failed` receipts and receipts with an
   old `parser_version`.

**Stage 2: analytics**

6. **Spending** `/stats`. Week, month or a custom period. Broken down by category, store
   and card, compared with the previous period.

**Stage 3: later**

7. Manual receipt entry without a photo.
8. Monthly budgets per category, with a notice when a budget is exceeded.
9. CSV / XLSX export.
10. Shopping list from purchase frequency.
11. Whitelist management from the bot, for the admin only.

## Duplicate photos and receipts

Checks run in this order when a photo arrives:

1. **Same image.** The Telegram `file_unique_id` is already stored for this user → reply
   "already have this photo", with no LLM call.
2. **Same receipt.** After parsing, the `receipt_key` equals a `parsed` receipt of the
   same user → the new receipt is marked `duplicate` and the user is told which receipt
   it repeats, with a button to open it.
3. Otherwise it is a new receipt.

A re-parse (same photo, newer parser version, run from a maintenance command) replaces
the parse; the user's edits stay on top, and a disagreement between a re-parse and an
edit becomes an issue. `receipt_items` are rebuilt in one transaction; `store_products`
rows that only this receipt created and nothing else references are deleted.

## Dialogs (aiogram-dialog)

### Photo intake

A plain handler, not a dialog, so that a photo is accepted in any state.

```
[photo] → ✅ Saved, reading…
        → 🧾 Mercadona · 14.10.2026 18:32
          Total 47.85 € · VISA •1234 · 23 items
          ⚠️ 2 to review
          [📋 Items] [🖼 Photo] [🗑 Delete]
```

A bad reading: the user taps `🗑 Delete` and sends a better photo.

The buttons are a plain inline keyboard under every parse reply (parsed, not a receipt,
duplicate, failed). A tap starts the `ReceiptCard` dialog with `receipt_id` in
`start_data`, as a new message; the summary is never edited and keeps its buttons. A tap on
a deleted receipt answers with an alert and removes the keyboard. A photo sent while a card
is open is still accepted.

### ReceiptCard

| window | content |
|---|---|
| `main` | summary and buttons (`Delete`, `Close`); a receipt that is not `parsed` shows its status, the photo's date and, for a duplicate, the receipt it repeats |
| `items` | paginated item list (`ScrollingGroup`); a tap opens `item` |
| `item` | `[✏️ Name] [🏷 Category] [🔢 Qty/price]` |
| `issues` | one issue per screen: `[✅ Correct] [✏️ Enter value] [⏭ Skip]` |
| `photo` | sends the stored photo |
| `delete_confirm` | confirms the delete (soft delete; the photo moves to the trash). Refused while the receipt is being read |

An issue screen looks like this:

```
Date read as 14.10.2025, photo sent on 14.10.2026.
I used 14.10.2026.
[✅ Correct] [✏️ Enter date] [⏭ Skip]
```

### History (`/receipts`)

```
October 2026 · 12 receipts · 384.20 €
[◀ Sep] [Store ▾] [Nov ▶]
• 14.10 Mercadona   47.85 €
• 12.10 Lidl        23.10 €
```

A row opens `ReceiptCard`.

### Main menu (`/start`)

`[🧾 Receipts] [📊 Spending]`. Only Receipts works in stage 1.
