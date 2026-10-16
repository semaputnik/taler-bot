# taler-bot

A Telegram bot that reads photos of household purchase receipts and keeps what was
bought, where and for how much.

## Language

**Receipt**:
One purchase, as a whole: its photo, the parse made of it, the items, the issues and the
user's edits. The unit that must stay consistent when anything changes.
_Avoid_: payment (n8n name), ticket, check

**Photo**:
The one image a receipt was read from. A bad photo is not replaced: the user deletes the
receipt and sends a new one.

**Parse**:
The reading of a receipt's photo by the LLM, normalized. A receipt has at most one; a
re-parse (for example with a newer parser version) replaces it.
_Avoid_: extraction, OCR result

**Header**:
The receipt-level facts: store, purchase time, totals, payment, card. Always the parse
with the edits applied.

**Item**:
One product line of the parse: quantity, unit, price, line total.
_Avoid_: line, price row, product_price (n8n name)

**Issue**:
A doubt noted while reading a receipt: by the model, by normalization, or because a
re-parse disagrees with an edit. The user confirms, corrects or skips it.
_Avoid_: warning, error, problem

**Edit**:
A value the user corrected by hand on a receipt or one of its items. Edits always win
over any parse, including a later re-parse.
_Avoid_: override, correction

**Re-parse**:
Read the same photo again, for example with a newer parser version, and replace the
parse. Edits stay on top.
_Avoid_: refine, refresh

**Receipt key**:
The text that identifies a receipt: store, receipt number, day and total. Two parsed
receipts of one user never share it, so the same receipt photographed twice is refused.

**Store**:
A shop, identified per user by the slug of its trading name.
_Avoid_: merchant, vendor

**Product**:
A catalogue entry for one store: the printed line text, a readable name and a category.
Created by the first receipt that shows it and never overwritten by a parse, so names
and categories can be fixed by hand.
_Avoid_: store product (the table name), SKU, article

**Catalog**:
A user's stores and their products. Outlives any receipt.

**Normalize**:
Turn the raw LLM output into a parse: keys for store, receipt and products, units,
corrected dates, sanity checks and the issues they raise.

**Allowed user**:
A Telegram user who may use the bot. Anyone else is recorded but never answered.
_Avoid_: whitelisted user, admin (a separate flag)
