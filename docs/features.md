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
1. **Receipt card.** The parse reply is the card, with inline buttons: `Items`, `Photo`, `Delete`
   `Review (n)` appears when issues wait. Done (items are read-only until the item-edit spec).
2. **Issue review.** Walk through high/medium issues one at a time. For each, confirm the
   assumed value or enter the right one (date, total, card last 4, lines that don't add up).
   The walk with `Correct`, `Skip` and the tally is done; the value entry is next.
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

A plain handler, not a dialog, so that a photo is accepted in any state. The
"✅ Saved, reading…" reply is a plain message (a reply to the photo); the parse result is the
`ReceiptCard` dialog's `main` window, started by the background task as a new message.

```
[photo] → ✅ Saved, reading…
        → 🧾 Mercadona · 14.10.2026 18:32
          Total 47.85 € · VISA •1234 · 23 items
          ⚠️ 2 to review
          [📋 Items] [🖼 Photo] [🗑 Delete]
```

A bad reading: the user taps `🗑 Delete` and sends a better photo.

The parse reply is the card for every outcome (parsed, not a receipt, duplicate, failed):
the `main` window shows the matching text and its buttons. It is not a reply to the photo
(a dialog message has no reply parameters). The buttons are plain callback buttons rendered
inside the dialog, so they work on a card however old. A tap on the current card (the
dialog's last message) edits it in place. A tap on an older card sends a fresh card message
and leaves the old card with its buttons. A tap on a deleted receipt answers with an alert
and removes the keyboard. A photo sent while a card is open is still accepted. `✖ Close`
hides the card's buttons and keeps its text; the resting state of a card is `main`.

### ReceiptCard

| window | content |
|---|---|
| `main` | the parse reply: the summary and buttons (`Items`, `⚠️ Review (n)` when n > 0, `Photo`, `Delete`); a receipt that is not `parsed` shows the outcome text (not a receipt, failed, duplicate with the receipt it repeats, waiting, being read) and the photo's date; a deleted receipt shows "🗑 This receipt was deleted." and no buttons |
| `items` | paginated item list (`ScrollingGroup`, 8 per page); a tap opens `item` |
| `item` | all parsed fields, read-only; `[✏️ Name] [🏷 Category] [🔢 Qty/price]` arrive with item edit |
| `issue` | one issue per screen: `[✅ Correct] [✏️ Enter value] [⏭ Skip] [◀ Back]`; `✏️` only for an editable issue. `Correct` and `Skip` move on to the next issue |
| `issue_input` | "Enter the total (a number with a point, like 12.50)" and a text input; `◀ Back` returns to `issue`. The text is read by the issue's input kind (date and time `dd.mm.yyyy hh:mm` in the user's time zone, number with a point or comma, four digits, 3-letter currency, free text). A wrong value or a non-text message keeps the window with an error line and the issue open; a good one is saved as an edit, the issue is marked corrected and the walk moves on |
| `review_done` | the tally ("3 reviewed: 1 corrected, 1 confirmed, 1 skipped") and `◀ Back` to `main` |
| `photo` | the stored photo by Telegram file id, uploaded from disk if Telegram refuses the id |
| `delete_confirm` | confirms the delete (soft delete; the photo moves to the trash). Refused while the receipt is being read. After a delete the card shows `main` in its deleted form |

The `⚠️ Review (n)` button sits in `main` (between Items and Photo),
only when `n` high or medium issues wait. The walk is loaded once on entry, high first, then
parse order; an issue resolved elsewhere is skipped silently. A skipped issue stays counted
on the button and comes back in the next walk. An issue screen looks like this:

```
⚠️ Issue 2 of 5 🟡

Item: Cervesa Free Limo
Line math is off.

Current value: 4.80 €
[✅ Correct] [✏️ Enter value]
[⏭ Skip] [◀ Back]
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
