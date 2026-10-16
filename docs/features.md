# Features and dialogs

Agreed with the user on 2026-10-16. The MVP scope is not planned yet. Stages describe order
and dependencies, not commitments.

## Decisions

- **Data belongs to the Telegram user** the bot is talking to. Every row is scoped by
  `user_id`. A household or shared view is out of scope for now.
- **The UI is in English.** All texts live in fluentogram `.ftl` files (`en` locale);
  another language is one more locale directory.
- **Several photos per receipt.** A second photo of a known receipt refines the stored
  data instead of being thrown away (see below). Refinements are **applied immediately**,
  and the user can undo them.
- Dropped: price lookup across stores (`/price`) and price-rise alerts. There is no
  canonical-product table.

## Stages

**Stage 0: n8n parity.** Photo → save → parse → summary. Covers "not a receipt",
failures and repeat photos (repeats now feed the multi-photo flow below).

**Stage 1: working with a receipt after parsing**
1. **Receipt card.** Inline buttons under the summary: items, photo, review issues, add
   photo, delete.
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

## Multi-photo receipts

### Attaching a photo to an existing receipt

Checks run in this order:

1. **Same image.** The Telegram `file_unique_id` is already stored for this user → reply
   "already have this photo", with no LLM call.
2. **Explicit.** The photo is sent as a reply to the bot's receipt summary, or after the
   `📷 Add photo` button. It attaches to that receipt even if the keys differ, which
   covers a misread receipt number.
3. **Automatic.** The new photo is parsed alone first. If its `receipt_key` equals a
   `parsed` receipt of the same user, the photo attaches to that receipt.
4. **Near match.** Same store and day, but the receipt number or total differs → ask:
   ```
   Looks like Mercadona, 14 Oct (47.85 €). Same receipt?
   [Yes, refine it] [No, it's a new one]
   ```
5. Otherwise it is a new receipt.

This also covers long receipts photographed in parts.

### Refining

- Re-parse with **all photos of the receipt in one LLM call** (several `BinaryContent`
  images). The model does not see the previous parse, so it cannot repeat its mistakes.
  Prompt addition: the images are photos of one receipt; merge them into one result and
  report in `issues` where the photos disagree.
- Normalize as usual, diff against the current state, and apply the result at once.
- **User edits win.** A field the user corrected by hand is never overwritten. If the
  new parse reads it differently, add an issue instead.
- `receipt_items` for the receipt are rebuilt in one transaction. `store_products` rows
  that this receipt created and nothing else references are deleted (they are misreads).
- Undo restores the previous parse together with the user edits.

### Data model additions

- `receipt_photos`: receipt_id, user_id, path (relative to `RECEIPTS_DIR`),
  telegram_file_unique_id, telegram_message_id, received_at.
- `receipt_parses`: receipt_id, raw_json, model, parser_version, photo ids used,
  created_at. The receipt points at its current parse. Undo switches it back.
- User edits: stored per receipt, field and item, separately from parses, so a re-parse
  can apply them on top.

## Dialogs (aiogram-dialog)

### Photo intake

A plain handler, not a dialog, so that a photo is accepted in any state.

```
[photo] → ✅ Saved, reading…
        → 🧾 Mercadona · 14.10.2026 18:32
          Total 47.85 € · VISA •1234 · 23 items
          ⚠️ 2 to review
          [📋 Items] [⚠️ Review (2)] [📷 Add photo] [🗑 Delete]
```

After a refinement:

```
🔁 Same receipt: Mercadona · 14.10.2026 (photo 2 of 2)
Updated from the new photo:
• Total: 47.58 → 47.85 €
• "LECHE ENT. HAC" → "Leche entera Hacendado 1 l"
• Added line: Pan de molde 1.35 €
⚠️ 1 to review (was 3)
[📋 Items] [⚠️ Review (1)] [↩️ Undo]
```

The buttons start the `ReceiptCard` dialog with `receipt_id` in `start_data`.

### ReceiptCard

| window | content |
|---|---|
| `main` | summary and buttons |
| `items` | paginated item list (`ScrollingGroup`); a tap opens `item` |
| `item` | `[✏️ Name] [🏷 Category] [🔢 Qty/price]` |
| `issues` | one issue per screen: `[✅ Correct] [✏️ Enter value] [⏭ Skip]` |
| `photos` | sends the stored photos |
| `add_photo` | waits for a photo and attaches it explicitly |
| `delete_confirm` | confirms the delete |

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
