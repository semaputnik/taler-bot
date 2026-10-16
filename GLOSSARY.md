# taler-bot

A Telegram bot that reads photos of household purchase receipts and keeps what was
bought, where and for how much.

## Language

**Receipt**:
One purchase, as a whole: its photos, every parse made of them, the items, the issues
and the user's edits. The unit that must stay consistent when anything changes.
_Avoid_: payment (n8n name), ticket, check

**Photo**:
One image of a receipt. A receipt may have several, for example a second shot that
refines the first or the two halves of a long receipt.

**Parse**:
One reading of a receipt's photos by the LLM, normalized. A receipt keeps every parse
it ever had and points at the current one.
_Avoid_: extraction, OCR result

**Current parse**:
The parse the receipt's header and items are built from. Undo switches it back to an
earlier parse.

**Header**:
The receipt-level facts: store, purchase time, totals, payment, card. Always the
current parse with the edits applied.

**Item**:
One product line of the current parse: quantity, unit, price, line total.
_Avoid_: line, price row, product_price (n8n name)

**Issue**:
A doubt noted while reading a receipt: by the model, by normalization, or by a
disagreement between photos or with an edit. The user confirms, corrects or skips it.
_Avoid_: warning, error, problem

**Edit**:
A value the user corrected by hand on a receipt or one of its items. Edits always win
over any parse.
_Avoid_: override, correction

**Refine**:
Re-parse a receipt from all of its photos after a new one arrives, then apply the result
at once. The user can undo it.
_Avoid_: re-parse (the mechanism, not the action), update, merge (that is for two receipts)

**Merge**:
Attach a photo that arrived as its own receipt to the receipt it belongs to. The
source receipt stays, marked `merged`, pointing at the target.
_Avoid_: deduplicate, duplicate

**Near match**:
A receipt from the same store on the same day whose number or total differs from a new
one. The bot asks the user whether they are the same receipt.

**Receipt key**:
The text that identifies a receipt for matching: store, receipt number, day and total.
Two parsed receipts of one user never share it.

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
