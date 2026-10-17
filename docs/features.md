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
1. **Receipt card.** The parse reply is the card, with inline buttons: `Items`, `Photo`, `Delete`,
   `Re-parse` (when the receipt can be read again) and `Close`.
   `Review (n)` appears when issues wait. Done (items are read-only until the item-edit spec).
2. **Issue review.** Walk through high/medium issues one at a time. For each, confirm the
   assumed value or enter the right one (date, total, card last 4, lines that don't add up).
   The walk with `Correct`, `Skip` and the tally is done; the value entry is next.
3. **Item edit.** Name, category, quantity/price. Name and category are saved to
   `store_products`, so future receipts pick them up. Done, including `Rename` from the
   issue review.
4. **Receipt history** `/receipts`. Paginated, filtered by month and store; a row opens
   the card.
5. **Reparse.** One receipt by hand, or in bulk for `failed` receipts and receipts with an
   old `parser_version`. Done. The card's `🔄 Re-parse` button reads one receipt again. The
   `/reparse` command shows "N failed · M read by an older parser (now <version>)" with the
   buttons `🔁 Re-parse failed (N)` and `🔁 Re-parse outdated (M)` (each only when its count is
   above 0). A tap edits the message to "🔁 Re-parsing N receipts…", reads up to 50 receipts one
   after the other in the background and replies "Re-parsed 12: 10 ok, 2 failed". A second tap
   while a run is going answers an alert.

**Stage 2: analytics**

6. **Spending** `/stats`. One week or month of spending against the previous period. The
   message is plain text with plain callback buttons, like the history:
   ```
   📊 October 2026
   384.20 € · 12 receipts · ▲ 8% vs September (355.10 €)

   Categories
   • Groceries 300.00 € · 78% · ▲ 9%
   • Rent 80.00 € · 21% · new
   • Restaurants 4.20 € · 1%

   Groceries by product
   • Produce 146.00 € · 49% · ▲ 12%
   • Dairy 73.00 € · 24% · ▼ 5%
   • Not itemised 81.00 € · 27%

   Payees
   • Mercadona 210.00 € · 55% · ▲ 3%
   • Landlord 80.00 € · 21% · new
   • Consum 90.00 € · 23% · new

   Payment sources
   • VISA •0848 300.00 € · ▲ 10%
   • Cash 84.20 €
   ```
   Since stage 3 the sections are: expense categories over all expenses, `Groceries by
   product` (hidden when no receipt has items), payees (the top five) and payment sources
   (cards and cash by name).
   - A week reads `📊 Week 42 · 13.10–19.10.2026` (ISO week number, Monday to Sunday).
   - Stage 2 read categories from the item lines, as a bulleted list with the share in percent; the part no item covers is `Not itemised`. Stores (the top five) and
     cards came from the receipt totals. A line shows `▲ 12%`, `▼ 5%` or `new`; nothing is
     compared when the previous period has no receipts.
   - One block per currency, headed by the currency when there is more than one. An empty
     period shows its title and "No purchases in this period."
   - Buttons: `[◀ Sep] [Nov ▶]` (`◀` always, an empty period says so; `▶` only in a past
     period; a week's labels are its neighbours' start dates), `[📅 Week]` or `[📅 Month]` (the
     other kind, anchored on this period's start), and `[🧾 Receipts]` on the month screen,
     which sends that month's history as a new message. Taps edit the message in place.

**Stage 3: the bot becomes an expense manager** (agreed on 2026-10-17, ADR-0003)

Receipts are no longer entered by hand; instead every outflow of money is an **expense**, and
a receipt is one way of entering an expense with full detail. An expense has an amount (the
default currency for now), a date, a payee, a payment source (a card or cash), an expense
category, tags, and optionally the receipt it came from.

7. **Expense model and migration.** `Expense`, `Payee` (generalises `Store`), `PaymentSource`
   (cards from receipts and by hand, plus cash), `ExpenseCategory` (groceries, restaurants,
   transport, rent, utilities, health, entertainment, subscriptions, clothing, travel, gifts,
   other) and tags. Every existing receipt becomes an expense (`groceries`, payee = its store,
   source by its card ending or cash, date = purchase date; a deleted receipt gives a deleted
   expense). `/stats` reports by expense category first, then "Groceries by product", payees and
   payment sources. **Done.** The receipt card shows `Category: Groceries` after the payment
   line and a `🏷 Category` button (the twelve categories, two per row, `✓` on the current one)
   when the receipt has an expense; a failed, duplicate or not-a-receipt card shows neither.
   `/receipts` lists the expenses of the month plus the receipts that have no expense (with
   their status icon), so a failed or duplicate receipt stays reachable for deleting.
8. **Manual entry.** A message that is only a number (`12.50`, `12,50`, `7`) starts the entry
   with that amount: payee (the five most recent as buttons, or typed; a typed name matching an
   existing payee reuses it) → payment source (cards, `Cash`, `➕ New card`) → category → date
   (`Today`, `Yesterday`, `dd.mm`) → tags (comma-separated or `Skip`) → the expense card. Every
   step has `◀ Back`. Only expenses: amounts are positive.
9. **Expense card.** One card for every expense. With a receipt it is the receipt card plus
   `Category` and `Tags`. Without one: amount, payee, source, category, date, tags; buttons
   `✏️ Amount` `🏪 Payee` / `💳 Source` `🏷 Category` / `📅 Date` `#️⃣ Tags` / `🗑 Delete` /
   `✖ Close`; no items, photo, review or re-parse. `💳 Source` offers `✏️ Rename` for a card.
10. **History `/expenses`** replaces `/receipts`: every expense of the month, a receipt icon on
    those read from a photo; filter by payee.
11. **Expiring screens.** Screens opened by a command or a menu button (`/start`, `/expenses`,
    `/stats`, the `/reparse` summary, an unfinished entry) are deleted after
    `SCREEN_TTL_MINUTES` (30) without a tap; a tap extends the time. Cards, "Saved, reading…",
    error replies and re-parse results stay. Tracked in Redis so it survives a restart.

**Later**

- Menus to rename and merge payees and to rename cards (today only from an expense card).
- Attaching a receipt photo to an existing expense; a currency per expense; one-line entry
  (`12.50 Mercadona`); income and refunds.
- Monthly budgets per expense category with a notice when exceeded; CSV / XLSX export;
  shopping list from purchase frequency; whitelist management from the bot.

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
`🔄 Re-parse` first asks for a confirmation (a model call costs money); `🔄 Yes, read again` replies "🔄 Reading again…" to the card, shows the typing status while the
receipt is read, then sends a fresh card with the new reading (or the old reading and the
error line if the read failed); the old card keeps its buttons. A stale button on a receipt
that can no longer be read again (duplicate, deleted) answers an alert.

### ReceiptCard

| window | content |
|---|---|
| `main` | the parse reply: the summary and buttons (`Items`, `⚠️ Review (n)` when n > 0, `🏷 Category` when the receipt has an expense, `Photo`, `Delete`, and `🔄 Re-parse` on its own row when the receipt is `parsed`, `failed` or `not_receipt`); a `Category: Groceries` line after the payment line when the receipt has an expense (a failed, duplicate or not-a-receipt card has neither line nor button); the error line (`⚠️ The last reading failed: …`) is added when the last read failed, also on a parsed card that kept its previous reading; a receipt that is not `parsed` shows the outcome text (not a receipt, failed, duplicate with the receipt it repeats, waiting, being read) and the photo's date; a deleted receipt shows "🗑 This receipt was deleted." and no buttons |
| `items` | paginated item list (`ScrollingGroup`, 8 per page); a tap opens `item` |
| `item` | all parsed fields, and the edit buttons `[✏️ Name] [🏷 Category]`, `[🔢 Quantity] [💶 Unit price]`, `[🧾 Line total]`, `[◀ Back]` |
| `item_input` | "Enter the quantity (a number with a point, like 1.5)" with the current value, and a text input; `◀ Back` returns to `item`. Read like the review's input (`text` for the name, `number` for quantity and unit price, `money` for the line total). A wrong value (text, empty name, zero or negative quantity, negative price) keeps the window with an error line and changes nothing. The name is saved to the catalog and changes the product on every receipt of the store; the numbers are saved as edits of this receipt and survive a re-parse. A good value returns to `item` with the new value; a receipt deleted meanwhile gives the deleted alert and `main` |
| `item_category` | the 15 categories, two per row, the current one marked `✓`, and `◀ Back` to `item`. A tap saves the category to the catalog (every receipt showing the product) and returns to `item` |
| `category` | the twelve expense categories, two per row, the current one marked `✓`, and `◀ Back` to `main`. A tap sets the expense category and returns to `main`; a receipt deleted meanwhile, or one without an expense, gives the deleted alert and `main` |
| `issue` | one issue per screen: `[✅ Correct] [✏️ Enter value] [⏭ Skip] [◀ Back]`; `✏️ Enter value` only for an editable issue, and `✏️ Rename` in its place for a name issue whose item is matched to a product (never both). `Correct` and `Skip` move on to the next issue |
| `issue_rename` | "Enter the name (free text)" with the product's current name, and a text input; `◀ Back` returns to `issue` with the issue open. A good name renames the product in the catalog (every receipt of the store), marks the issue corrected and moves the walk on; an empty name or a non-text message keeps the window with an error line; a receipt deleted meanwhile gives the deleted alert and `main`; an issue resolved elsewhere meanwhile is skipped silently |
| `issue_input` | "Enter the total (a number with a point, like 12.50)" and a text input; `◀ Back` returns to `issue`. The text is read by the issue's input kind (date and time `dd.mm.yyyy hh:mm` in the user's time zone, number with a point or comma, four digits, 3-letter currency, free text). A wrong value or a non-text message keeps the window with an error line and the issue open; a good one is saved as an edit, the issue is marked corrected and the walk moves on |
| `review_done` | the tally ("3 reviewed: 1 corrected, 1 confirmed, 1 skipped") and `◀ Back` to `main` |
| `photo` | the stored photo by Telegram file id, uploaded from disk if Telegram refuses the id |
| `reparse_confirm` | "Read this receipt again? …" with `🔄 Yes, read again` and `◀ Back` |
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
[✅ Correct] [✏️ Enter value]  (a name issue shows [✏️ Rename] instead)
[⏭ Skip] [◀ Back]
```

### History (`/receipts`)

One month of the user's receipts (month by purchase date, the day the photo arrived as the
fallback, in the user's time zone), newest first, eight rows per page. A plain callback
keyboard, not a dialog: every button carries the month, the store filter and the page, so the
message keeps working however old it is and however many cards were opened from it.

```
🗓 October 2026 · Mercadona
12 receipts · 384.20 €
[• 14.10 Mercadona · 47.85 €]
[• 12.10 Lidl · 23.10 €]
[• 11.10 Consum · ❌]
[◀ Sep] [Store ▾] [Nov ▶]
[◀] [2/3] [▶]
```

- The summary counts parsed receipts only, with one total per currency. A month without any
  says so (`No receipts this month.`, or `No parsed receipts`).
- A row without an amount shows ❌ failed, ♻️ duplicate, 🤔 not a receipt, ⏳ pending or parsing.
- `◀ Sep` / `Nov ▶` appear only when a receipt lies before / after the month (never past the
  current month). The paging row appears only with more than one page, and its arrows only
  where there is a page to go to.
- `Store ▾` lists the stores with receipts in the month, `✓` on the selected one, `All stores`
  and `◀ Back`. The filter stays while moving between months and pages.
- A row opens the receipt's card as a new message; the history keeps its buttons.

### Main menu (`/start`)

The greeting carries `[🧾 Receipts]` and `[📊 Spending]`, which send the current month's history
and stats as new messages. Stage 3 renames the first to `[💸 Expenses]`.
