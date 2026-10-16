const ai = $('Parse Receipt').first().json.output;
const file = $('Extract Receipt File').first().json;
const drive = $('Attach Receipt Image').first().json;
let model = null;
try { model = $('OpenAI Model').params.model?.value ?? null; } catch (e) {}
// Both lookups run with alwaysOutputData, so an empty table arrives as one empty item.
const knownProducts = $('Load Store Products').all().map((i) => i.json).filter((r) => r.productKey);
const pastPayments = $('Load Past Payments').all().map((i) => i.json).filter((r) => r.id && r.id !== drive.paymentId);

const strip = (s) => (s ?? '').toString().normalize('NFD').replace(/[̀-ͯ]/g, '');
const slug = (s) => strip(s).toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9а-яё]+/g, '-').replace(/^-+|-+$/g, '');
const clean = (s) => (s === null || s === undefined) ? null : (String(s).trim() || null);
const num = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(n) ? Math.round(n * 10000) / 10000 : null;
};
const round2 = (n) => Math.round(n * 100) / 100;
const UNITS = { pcs: 'pcs', pc: 'pcs', ud: 'pcs', uds: 'pcs', u: 'pcs', un: 'pcs', unit: 'pcs', units: 'pcs', 'шт': 'pcs', kg: 'kg', 'кг': 'kg', g: 'g', gr: 'g', 'г': 'g', l: 'l', lt: 'l', 'л': 'l', ml: 'ml', 'мл': 'ml' };
const unitOf = (u) => UNITS[strip(u).toLowerCase().replace(/[^a-zа-я]/g, '')] ?? (clean(u) ? strip(u).toLowerCase() : 'pcs');
const LEGAL_SUFFIX = /(^|\s)(s\.?\s?a\.?\s?u?\.?|s\.?\s?l\.?\s?u?\.?|ltd\.?|llc|gmbh|inc\.?|ооо|ип)(?=\s|$)/gi;

const issues = [];
const flag = (issueType, severity, field, message, itemName = null) =>
  issues.push({ source: 'workflow', issueType, severity, field, itemName, message });

const store = ai.store ?? {};
const storeName = clean(store.name) ?? clean(store.legal_name) ?? 'Unknown store';
const storeKey = slug(storeName.replace(LEGAL_SUFFIX, ' ')) || 'unknown-store';

const zone = 'Europe/Madrid';
const received = DateTime.fromSeconds(file.messageDate, { zone });
const printed = clean(ai.receipt?.purchased_at);
let purchased = printed ? DateTime.fromISO(printed, { zone }) : null;
if (purchased && !purchased.isValid) purchased = DateTime.fromSQL(printed, { zone });
if (!printed) flag('missing_field', 'medium', 'receipt.purchased_at', 'No purchase time on the receipt; used the Telegram message time.');
else if (!purchased.isValid) flag('ambiguous', 'high', 'receipt.purchased_at', 'Unparseable purchase time "' + printed + '"; used the Telegram message time.');
if (!purchased || !purchased.isValid) purchased = received;
// A receipt is photographed shortly after the purchase. A date far from the message date is almost always a
// misread year, which would also shift the duplicate key and the price history, so try the message's year first.
const earliest = received.minus({ days: 60 });
const latest = received.plus({ days: 1 });
if (purchased < earliest || purchased > latest) {
  const read = purchased.toISODate();
  const fixed = [purchased.set({ year: received.year }), purchased.set({ year: received.year - 1 })]
    .find((d) => d.isValid && d >= earliest && d <= latest);
  if (fixed) {
    purchased = fixed;
    flag('corrected', 'medium', 'receipt.purchased_at', 'Read the date as ' + read + ', but the photo was sent on ' + received.toISODate() + '; assumed a misread year and used ' + fixed.toISODate() + '.');
  } else {
    flag('ambiguous', 'high', 'receipt.purchased_at', 'Purchase date ' + read + ' is far from the date the photo was sent (' + received.toISODate() + '); kept as read, check the receipt.');
  }
}
const purchasedAt = purchased.toISO();

const currency = (clean(ai.currency) ?? 'EUR').toUpperCase();
const totals = ai.totals ?? {};
const total = num(totals.total) ?? num(ai.payment?.amount_paid);
// Duplicate key. Store name, receipt number and money read the same across runs; the printed minute and the
// tax id (often blurry, sometimes null) do not. The date stays in the key because some stores restart
// receipt numbering every day.
const receiptNo = (clean(ai.receipt?.number) ?? '').toUpperCase().replace(/\s+/g, '');
const receiptKey = receiptNo
  ? [storeKey, receiptNo, purchased.toFormat('yyyy-MM-dd'), total ?? 'na'].join('|')
  : [storeKey, purchased.toFormat("yyyy-MM-dd'T'HH:mm"), total ?? 'na'].join('|');

const keyByRaw = {};
const items = (ai.items ?? [])
  .filter((it) => clean(it.name_normalized) || clean(it.name_raw))
  .map((it) => {
    const quantity = num(it.quantity) ?? 1;
    // Drop a leading "2 " / "2x " that repeats the quantity, so the product key does not change with the amount bought.
    const lead = (clean(it.name_raw) ?? '').match(/^(\d+(?:[.,]\d+)?)\s*[x×*]?\s+(.+)$/i);
    const nameRaw = lead && num(lead[1]) === quantity ? lead[2].trim() : clean(it.name_raw);
    const productName = clean(it.name_normalized) ?? nameRaw;
    const lineTotal = num(it.line_total);
    const unit = unitOf(it.unit);
    const referencePrice = num(it.reference_price);
    const referenceUnit = clean(it.reference_unit) ? unitOf(it.reference_unit) : null;
    const unitPrice = num(it.unit_price)
      ?? (referenceUnit === unit ? referencePrice : null)
      ?? (lineTotal !== null && quantity ? Math.round((lineTotal / quantity) * 10000) / 10000 : null);
    // The printed line text comes from the store's POS and is stable across receipts; the LLM's normalized name is not.
    const productKey = storeKey + '::' + (slug(nameRaw) || slug(productName));
    if (clean(it.name_raw)) keyByRaw[clean(it.name_raw)] = productKey;
    return {
      productKey,
      productName,
      productNameRaw: nameRaw ?? productName,
      category: clean(it.category) ?? 'other',
      quantity,
      unit,
      unitPrice,
      referencePrice,
      referenceUnit,
      discount: num(it.discount) ?? 0,
      lineTotal,
      vatRate: num(it.vat_rate),
    };
  });

const last4 = (clean(ai.payment?.card_last4) ?? '').replace(/\D/g, '').slice(-4) || null;

// Name notes on a product already in store_products repeat on every receipt that has it, and its name there
// has already been settled (or corrected by hand), so they are dropped.
const knownKeys = new Set(knownProducts.map((p) => p.productKey));
const NAME_NOTES = new Set(['unknown_abbreviation', 'ambiguous']);
for (const i of ai.issues ?? []) {
  const itemName = clean(i.item_name_raw);
  const key = itemName ? (keyByRaw[itemName] ?? storeKey + '::' + slug(itemName)) : null;
  if (key && NAME_NOTES.has(i.type) && (clean(i.field) ?? '').startsWith('items.name') && knownKeys.has(key)) continue;
  issues.push({
    source: 'model',
    issueType: i.type ?? 'other',
    severity: i.severity ?? 'medium',
    field: clean(i.field),
    itemName,
    message: clean(i.message) ?? '',
  });
}

if (storeKey === 'unknown-store') flag('missing_field', 'high', 'store.name', 'Store name not recognised; products are keyed under unknown-store.');
if (total === null) flag('missing_field', 'high', 'totals.total', 'No total on the receipt.');
if (!clean(ai.currency)) flag('missing_field', 'low', 'currency', 'No currency on the receipt; assumed EUR.');
if (clean(ai.payment?.card_last4) && !/^\d{4}$/.test(last4 ?? '')) flag('ambiguous', 'low', 'payment.card_last4', 'Card digits "' + ai.payment.card_last4 + '" are not 4 digits.');
// The household pays with a handful of cards, so an unseen ending is more often a misread digit than a new card.
const knownCards = [...new Set(pastPayments.map((p) => clean(p.cardLast4)).filter(Boolean))];
if (last4 && /^\d{4}$/.test(last4) && knownCards.length && !knownCards.includes(last4))
  flag('ambiguous', 'medium', 'payment.card_last4', 'Card ending ' + last4 + ' has not been seen before (known: ' + knownCards.join(', ') + '); check for a misread digit, ignore if it is a new card.');
if (ai.is_receipt !== false && items.length === 0) flag('missing_field', 'high', 'items', 'No product lines extracted.');
for (const it of items) {
  if (it.lineTotal === null) flag('missing_field', 'medium', 'items.line_total', 'Line has no total.', it.productNameRaw);
  else if (it.unitPrice !== null && Math.abs(round2(it.quantity * it.unitPrice - it.discount) - it.lineTotal) > 0.02)
    flag('totals_mismatch', 'medium', 'items.line_total', 'quantity × unit price − discount = ' + round2(it.quantity * it.unitPrice - it.discount) + ', line total is ' + it.lineTotal + '.', it.productNameRaw);
}

// Line totals are after line discounts; totals.discount_total is meant for receipt-wide discounts only, but the
// model sometimes repeats the line discounts there (printed as a separate "savings" line). Stored values are
// normalized so that subtotal − discountTotal = total: subtotal before any discount, discountTotal all discounts.
const linesSum = items.every((it) => it.lineTotal !== null) ? round2(items.reduce((s, it) => s + it.lineTotal, 0)) : null;
const lineDiscounts = round2(items.reduce((s, it) => s + it.discount, 0));
let receiptDiscount = num(totals.discount_total) ?? 0;
if (receiptDiscount > 0 && lineDiscounts > 0 && Math.abs(receiptDiscount - lineDiscounts) <= 0.02
    && linesSum !== null && total !== null && Math.abs(linesSum - total) <= 0.02) receiptDiscount = 0;
if (linesSum !== null && total !== null && Math.abs(round2(linesSum - receiptDiscount) - total) > 0.02)
  flag('totals_mismatch', 'high', 'totals.total', 'Lines add up to ' + linesSum + (receiptDiscount ? ' (minus receipt discount: ' + round2(linesSum - receiptDiscount) + ')' : '') + ', receipt total is ' + total + '.');
const discountTotal = round2(lineDiscounts + receiptDiscount);
const subtotal = linesSum !== null ? round2(linesSum + lineDiscounts) : num(totals.subtotal);

return [{
  json: {
    paymentId: drive.paymentId,
    parserVersion: file.parserVersion,
    model,
    processedAt: DateTime.now().toISO(),
    isReceipt: ai.is_receipt !== false,
    receiptKey,
    purchasedAt,
    storeKey,
    storeName,
    storeLegalName: clean(store.legal_name),
    storeAddress: [clean(store.address), clean(store.city)].filter(Boolean).join(', ') || null,
    storeTaxId: clean(store.tax_id),
    receiptNumber: clean(ai.receipt?.number),
    currency,
    subtotal,
    discountTotal,
    taxTotal: num(totals.tax_total),
    total,
    paymentMethod: clean(ai.payment?.method)?.toLowerCase() ?? null,
    cardBrand: clean(ai.payment?.card_brand)?.toUpperCase() ?? null,
    cardLast4: last4,
    itemsCount: items.length,
    driveFileId: drive.driveFileId,
    driveUrl: drive.driveUrl,
    telegramMessageId: file.messageId,
    chatId: file.chatId,
    rawJson: JSON.stringify(ai),
    issues,
    items,
  },
}];

