start-greeting =
    Hello, { $first_name }! I read photos of your purchase receipts. Send me one to get started.
    { "" }
    Send an amount like 12.50 to record an expense.

photo-send-me-one = Send me a photo of a receipt.
photo-too-large = This file is too large (the limit is 20 MB). Send a smaller photo.
photo-already-have = I already have this photo.

receipt-saved = ✅ Saved, reading…
reparse-started = 🔄 Reading again…
reparse-not-possible = This receipt cannot be read again.
reparse-summary = { $failed } failed · { $outdated } read by an older parser (now { $version })
reparse-none = Nothing to re-parse: every receipt was read by the current parser.
reparse-progress = 🔁 Re-parsing { $count } receipts…
reparse-done = Re-parsed { $total }: { $ok } ok, { $failed } failed
reparse-running = A re-parse is already running. I will report when it is done.
receipt-not-a-receipt = 🤔 This does not look like a receipt. Nothing was recorded.
receipt-duplicate = ♻️ Already recorded: <b>{ $store }</b>, { $date }, { $amount }

receipt-summary =
    🧾 <b>{ $store }</b>
    { "" }
    { $date }
    Total: <b>{ $amount }</b>
    Payment: { $payment }
receipt-category = Category: { $category }

expense-title = 💸 <b>{ $payee }</b>
expense-unknown-payee = Unknown payee
expense-amount = Amount: <b>{ $amount }</b>
expense-source = Paid with: { $source }
expense-tags = Tags: { $tags }
expense-payee-tag = #{ $tag }

entry-amount = 💸 <b>{ $amount }</b>
entry-payee = Who did you pay? Pick a recent payee or type a name.
entry-payee-name = Type the name of the payee.
entry-payee-name-error = ❌ The name needs letters or digits. Type it again.
entry-source = What did you pay with?
entry-new-card = Type a name for the new card, like Revolut.
entry-new-card-error = ❌ You already have a source with this name, or the name is empty. Type another.
entry-category = Pick the category of this expense.
entry-date = When was it?
entry-date-text = Type the date as dd.mm (this year) or dd.mm.yyyy.
entry-date-text-error = ❌ Not accepted. Send a date like 05.10 or 05.10.2026, not in the future.
entry-tags = Add tags separated by commas, like kids, holiday, or skip.
entry-tags-error = ❌ Not accepted. Use up to 10 tags of up to 32 characters each.
entry-pick-gone = That choice is no longer available. Pick again.

expense-deleted = 🗑 This expense was deleted.
expense-deleted-alert = This expense was deleted.
expense-delete-confirm = Delete this expense? It leaves your lists and statistics.
expense-edit-amount = Type the new amount. Now: <b>{ $amount }</b>
expense-edit-amount-error = ❌ Not accepted. Send an amount above zero, like 12.50.
expense-edit-rename = Type a new name for the card { $name }. It changes on every expense paid with it.
expense-edit-rename-error = ❌ You already have a source with this name, or the name is empty. Type another.
expense-edit-tags = Now: { $tags }. Type tags separated by commas, like kids, holiday, or clear them.
expense-edit-tags-error = ❌ Not accepted. Use up to 10 tags of up to 32 characters each.
receipt-items = Items: { $items }
receipt-store-tag = #{ $tag }
receipt-unknown-store = Unknown store
receipt-amount = { $total } { $currency }
receipt-amount-unknown = unknown
receipt-payment-card-brand = card { $brand } •{ $last4 }
receipt-payment-card = card •{ $last4 }
receipt-payment-method = { $method }
receipt-payment-none = not specified

card-deleted-alert = This receipt was deleted.
card-deleted = 🗑 This receipt was deleted.
card-status-pending = ⏳ Waiting to be read.
card-status-parsing = ⏳ Being read…
card-error = ⚠️ The last reading failed: { $reason }
card-received = Photo received: { $date }
card-delete-confirm = Delete this receipt? The photo is kept in the trash.
card-reparse-confirm = Read this receipt again? It takes up to two minutes and costs a model call. Your edits stay.
card-cannot-delete-parsing = This receipt is still being read. Try again in a moment.

card-items-title = 📋 Items ({ $count })

item-title =
    <b>{ $name }</b>
    { "" }
item-printed = <b>Printed as:</b> { $name }
item-category = <b>Category:</b> { $category }
item-quantity = <b>Quantity:</b> { $quantity } { $unit }
item-unit-price = <b>Unit price:</b> { $price }
item-reference-price = <b>Reference price:</b> { $price } per { $unit }
item-discount = <b>Discount:</b> { $amount }
item-line-total = <b>Line total:</b> { $amount }
item-vat = <b>VAT:</b> { $rate }%
item-amount = { $amount } { $sign }
item-not-specified = not specified
item-gone = This item is no longer on the receipt.
item-row = { $name } · { $quantity } { $unit } · { $total }

category-produce = Produce
category-greens = Greens
category-meat = Meat
category-fish = Fish
category-dairy = Dairy
category-bakery = Bakery
category-drinks = Drinks
category-alcohol = Alcohol
category-snacks = Snacks
category-frozen = Frozen
category-pantry = Pantry
category-household = Household
category-personal-care = Personal care
category-baby = Baby
category-pet = Pet
category-other = Other
category-current = ✓ { $name }
expense-category-groceries = Groceries
expense-category-restaurants = Restaurants
expense-category-transport = Transport
expense-category-rent = Rent
expense-category-utilities = Utilities
expense-category-health = Health
expense-category-entertainment = Entertainment
expense-category-subscriptions = Subscriptions
expense-category-clothing = Clothing
expense-category-travel = Travel
expense-category-gifts = Gifts
expense-category-other = Other
expense-category-prompt = Pick the category of this expense
category-not-possible = This receipt has no expense to categorise.
item-category-prompt = Pick the category for { $name }
item-input-prompt =
    Enter the { $field } ({ $hint })
    { "" }
    <b>Current value:</b> { $value }
card-photo-unavailable = The photo could not be loaded.

issue-title = ⚠️ <b>Issue { $position } of { $total }</b> { $icon }
issue-severity-high = 🔴
issue-severity-medium = 🟡
issue-item = <b>Item:</b> { $name }
issue-current-value = <b>Current value:</b> { $value }
issue-input-prompt = Enter the { $field } ({ $hint })
issue-input-error = ❌ Not accepted. Send { $hint }.
issue-input-gone = This issue is no longer open. Go back.

field-purchased-at = date and time
field-number = receipt number
field-currency = currency
field-total = total
field-subtotal = subtotal
field-discount-total = total discount
field-tax-total = total tax
field-method = payment method
field-card-last4 = card ending
field-name = name
field-quantity = quantity
field-unit-price = unit price
field-reference-price = reference price
field-discount = discount
field-line-total = line total
field-vat-rate = VAT rate, %

input-hint-datetime = dd.mm.yyyy hh:mm
input-hint-money = a number with a point, like 12.50
input-hint-number = a number with a point, like 1.5
input-hint-last4 = four digits
input-hint-currency = a 3-letter code, like EUR
input-hint-text = free text
review-done = { $reviewed } reviewed: { $corrected } corrected, { $confirmed } confirmed, { $skipped } skipped

history-title = 🗓 { $month } { $year }
history-title-filtered = 🗓 { $month } { $year } · { $store }
history-summary = { $count ->
    [one] 1 receipt
   *[other] { $count } receipts
  } · { $totals }
history-summary-none = No parsed receipts
history-empty = No receipts this month.
history-row = • { $day } { $store } · { $amount }
history-row-manual = 💸 { $day } { $store } · { $amount }
history-row-status = • { $day } { $store } · { $status }
history-page = { $page }/{ $pages }

month-1 = January
month-2 = February
month-3 = March
month-4 = April
month-5 = May
month-6 = June
month-7 = July
month-8 = August
month-9 = September
month-10 = October
month-11 = November
month-12 = December

month-short-1 = Jan
month-short-2 = Feb
month-short-3 = Mar
month-short-4 = Apr
month-short-5 = May
month-short-6 = Jun
month-short-7 = Jul
month-short-8 = Aug
month-short-9 = Sep
month-short-10 = Oct
month-short-11 = Nov
month-short-12 = Dec

stats-title-month = 📊 { $month } { $year }
stats-title-week = 📊 Week { $week } · { $from }–{ $to }
stats-headline = { $total } · { $count ->
    [one] 1 receipt
   *[other] { $count } receipts
  } · { $change } vs { $previous } ({ $previous_total })
stats-headline-no-previous = { $total } · { $count ->
    [one] 1 receipt
   *[other] { $count } receipts
  }
stats-previous-week = previous week
stats-empty = No purchases in this period.
stats-section-categories = <b>Categories</b>
stats-section-products = <b>Groceries by product</b>
stats-section-payees = <b>Payees</b>
stats-section-sources = <b>Payment sources</b>
stats-currency-block = <b>{ $currency }</b>
stats-line = • { $label } { $amount } · { $share }% · { $change }
stats-line-no-change = • { $label } { $amount } · { $share }%
stats-card-line = • { $label } { $amount } · { $change }
stats-card-line-no-change = • { $label } { $amount }
stats-change-up = ▲ { $percent }%
stats-change-down = ▼ { $percent }%
stats-change-same = ▬ 0%
stats-change-new = new
stats-not-itemised = Not itemised
