import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.domain.enums import IssueSeverity, IssueSource
from src.domain.normalize import PARSER_VERSION, normalize, slug
from src.exception import InvalidReceiptData

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "receipts"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))

# Where n8n's stored header differs from what its own normalizer returns for the stored raw
# output, because the household edited the row by hand afterwards. `normalize` returns the
# reading as the model gave it.
HAND_EDITED = {
    # 04: the model read no tax id; the stored row has the store's tax id, filled in by hand.
    "04-ametller-origen-parsed": {"storeTaxId": None},
    # 11: the model read the card as 0048 (normalize flags it, see the rule test below); the
    # stored row carries the corrected 0848.
    "11-ametller-origen-parsed": {"cardLast4": "0048"},
}


def load(stem: str):
    data = json.loads((FIXTURE_DIR / f"{stem}.json").read_text())
    ctx = data["context"]
    context = dict(
        received_at=datetime.fromisoformat(ctx["received_at"]),
        timezone=ctx["timezone"],
        known_product_keys=frozenset(ctx["known_product_keys"]),
        known_card_last4=frozenset(ctx["known_card_last4"]),
        parser_version=PARSER_VERSION,
        model="test-model",
    )
    return data["raw"], context, data["expected_n8n"]


def dec(x):
    return None if x is None else Decimal(str(x))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_normalize_reproduces_n8n(path):
    raw, context, exp = load(path.stem)
    exp = {**exp, **HAND_EDITED.get(path.stem, {})}
    parse = normalize(raw, **context)
    assert parse.receipt_key == exp["receiptKey"]
    if exp["status"] == "duplicate":
        # 06: n8n stored no header for the duplicate, only its receipt key (the same as 03's).
        assert (
            parse.receipt_key
            == normalize(*load("03-consum-parsed")[:1], **load("03-consum-parsed")[1]).receipt_key
        )
        return
    assert parse.purchased_at == datetime.fromisoformat(exp["purchasedAt"])
    assert parse.purchased_at.tzinfo is not None
    assert parse.store_key == exp["storeKey"]
    assert parse.store_name == exp["storeName"]
    assert parse.store_legal_name == exp["storeLegalName"]
    assert parse.store_address == exp["storeAddress"]
    assert parse.store_tax_id == exp["storeTaxId"]
    assert parse.receipt_number == exp["receiptNumber"]
    assert parse.currency == exp["currency"]
    assert parse.subtotal == dec(exp["subtotal"])
    assert parse.discount_total == dec(exp["discountTotal"])
    assert parse.tax_total == dec(exp["taxTotal"])
    assert parse.total == dec(exp["total"])
    assert parse.payment_method == exp["paymentMethod"]
    assert parse.card_brand == exp["cardBrand"]
    assert parse.card_last4 == exp["cardLast4"]
    assert len(parse.items) == exp["itemsCount"]
    assert parse.parser_version == PARSER_VERSION
    assert parse.model == "test-model"


def test_duplicate_fixture_has_the_key_of_the_original():
    dup = normalize(*load("06-unknown-duplicate")[:1], **load("06-unknown-duplicate")[1])
    original = normalize(*load("03-consum-parsed")[:1], **load("03-consum-parsed")[1])
    assert dup.receipt_key == original.receipt_key


# --- rule-level, on real receipts -------------------------------------------------------------


def run(stem, **override):
    raw, context, _ = load(stem)
    return normalize(raw, **{**context, **override})


def workflow_issues(parse):
    return [i for i in parse.issues if i.source is IssueSource.WORKFLOW]


def test_misread_year_is_corrected_to_the_message_year():
    parse = run("11-ametller-origen-parsed")
    assert parse.purchased_at.year == 2026
    [corrected] = [i for i in parse.issues if i.issue_type == "corrected"]
    assert corrected.source is IssueSource.WORKFLOW
    assert corrected.severity is IssueSeverity.MEDIUM
    assert "2025-10-14" in corrected.message


def test_unseen_card_ending_is_flagged_with_the_known_ones():
    parse = run("11-ametller-origen-parsed")
    [issue] = [i for i in workflow_issues(parse) if i.field == "payment.card_last4"]
    assert issue.severity is IssueSeverity.MEDIUM
    assert "0048" in issue.message
    assert "0848" in issue.message


def test_seen_card_ending_is_not_flagged():
    parse = run("12-mercadona-parsed")
    assert not [i for i in parse.issues if i.field == "payment.card_last4"]


def test_savings_line_is_not_double_counted():
    parse = run("11-ametller-origen-parsed")
    assert parse.discount_total == Decimal("0.09")
    assert parse.subtotal == Decimal("5.47")
    assert parse.total == Decimal("5.38")
    assert not [i for i in workflow_issues(parse) if i.field == "totals.total"]


def test_line_discounts_sum_into_the_discount_total():
    parse = run("09-iber-asia-parsed")
    assert parse.discount_total == Decimal("4.11")
    assert parse.subtotal == Decimal("20.53")
    assert parse.subtotal - parse.discount_total == parse.total


def test_item_without_quantity_gets_one_and_unit_price_from_the_line_total():
    raw, _, _ = load("12-mercadona-parsed")
    assert any(it["quantity"] is None for it in raw["items"])
    parse = run("12-mercadona-parsed")
    [salmon] = [i for i in parse.items if i.printed_name == "FILET SALMÓ"]
    assert salmon.quantity == Decimal(1)
    assert salmon.unit == "pcs"
    assert salmon.unit_price == salmon.line_total == Decimal("18.94")
    # n8n raised nothing of its own about this line.
    assert not [i for i in workflow_issues(parse) if i.item_name == "FILET SALMÓ"]


def model_name_notes(parse):
    return {i.item_name for i in parse.issues if i.field == "items.name_normalized"}


def test_name_notes_on_known_products_are_dropped():
    known = {"consum::ou-pages-1-2-dotz", "consum::aigua-c-g-pelegrino"}
    assert model_name_notes(run("07-consum-parsed")) == {"OU PAGES 1/2 DOTZ", "AIGUA C/G PELEGRINO"}
    assert model_name_notes(run("07-consum-parsed", known_product_keys=known)) == set()
    # 13 already knows OU PAGES; the other unknown products keep their notes.
    notes = model_name_notes(run("13-consum-parsed"))
    assert "OU PAGES 1/2 DOTZ" not in notes
    assert "A. BASMA BRILLANT P2" in notes


def test_name_notes_on_new_products_are_kept():
    assert model_name_notes(run("03-consum-parsed")) == {"CERV FREE LIMO."}


# --- synthetic: rules the fixtures do not hit --------------------------------------------------

CONTEXT = dict(
    received_at=datetime.fromisoformat("2026-10-12T16:00:00+00:00"),
    timezone="Europe/Madrid",
    known_product_keys=frozenset(),
    known_card_last4=frozenset(),
    parser_version=PARSER_VERSION,
    model=None,
)


def raw_receipt(*, store="Mercadona", number="123", items=None, total=3, **overrides):
    items = (
        [
            dict(
                name_raw="LECHE",
                name_normalized="Leche",
                category="dairy",
                quantity=1,
                unit="pcs",
                unit_price=total,
                line_total=total,
                discount=None,
                reference_price=None,
                reference_unit=None,
                vat_rate=None,
            )
        ]
        if items is None
        else items
    )
    base = dict(
        is_receipt=True,
        store=dict(name=store, legal_name=None, address=None, city=None, tax_id=None),
        receipt=dict(number=number, purchased_at="2026-10-12T17:30:00"),
        currency="EUR",
        items=items,
        totals=dict(subtotal=None, discount_total=None, tax_total=None, total=total),
        payment=dict(method="card", card_brand="visa", card_last4="1234", amount_paid=None),
        issues=[],
    )
    return {**base, **overrides}


def item(name_raw, **fields):
    base = dict(
        name_raw=name_raw,
        name_normalized=name_raw.title(),
        category=None,
        quantity=1,
        unit=None,
        unit_price=None,
        reference_price=None,
        reference_unit=None,
        discount=None,
        line_total=1,
        vat_rate=None,
    )
    return {**base, **fields}


def test_unknown_store_is_keyed_under_unknown_store_with_a_high_issue():
    parse = normalize(raw_receipt(store=None), **CONTEXT)
    assert parse.store_key == "unknown-store"
    assert parse.store_name == "Unknown store"
    [issue] = [i for i in workflow_issues(parse) if i.field == "store.name"]
    assert issue.severity is IssueSeverity.HIGH


def test_no_receipt_number_gives_a_time_based_key():
    parse = normalize(raw_receipt(number=None), **CONTEXT)
    assert parse.receipt_key == "mercadona|2026-10-12T17:30|3"


def test_receipt_number_key_uppercases_and_drops_spaces():
    parse = normalize(raw_receipt(number="ab 12/3"), **CONTEXT)
    assert parse.receipt_key == "mercadona|AB12/3|2026-10-12|3"


def test_leading_quantity_is_stripped_from_the_name_when_it_repeats_the_quantity():
    line = item("2 AIGUA GAS", quantity=2, line_total=2)
    parse = normalize(raw_receipt(items=[line], total=2), **CONTEXT)
    [only] = parse.items
    assert only.printed_name == "AIGUA GAS"
    assert only.product_key == "mercadona::aigua-gas"


def test_leading_number_that_is_not_the_quantity_stays():
    line = item("2 AIGUA GAS", quantity=3, line_total=3)
    parse = normalize(raw_receipt(items=[line], total=3), **CONTEXT)
    assert parse.items[0].product_key == "mercadona::2-aigua-gas"


@pytest.mark.parametrize(
    ("alias", "unit"),
    [
        ("ud", "pcs"),
        ("шт", "pcs"),
        ("Kg.", "kg"),
        ("кг", "kg"),
        ("lt", "l"),
        ("мл", "ml"),
        ("gr", "g"),
    ],
)
def test_unit_aliases(alias, unit):
    parse = normalize(raw_receipt(items=[item("X", unit=alias)], total=1), **CONTEXT)
    assert parse.items[0].unit == unit


def test_missing_unit_is_pieces_and_unknown_unit_is_kept_lowercase():
    parse = normalize(raw_receipt(items=[item("A"), item("B", unit="Pack")], total=2), **CONTEXT)
    assert [i.unit for i in parse.items] == ["pcs", "pack"]


def test_unit_price_falls_back_to_reference_price_in_the_same_unit_then_to_line_total():
    weighed = item(
        "FRUTA", unit="kg", quantity=Decimal("0.5"), reference_price=4, reference_unit="kg"
    )
    weighed["line_total"] = 2
    other = item("PAN", unit="pcs", reference_price=9, reference_unit="kg")
    other["quantity"] = 4
    other["line_total"] = 2
    parse = normalize(raw_receipt(items=[weighed, other], total=4), **CONTEXT)
    assert parse.items[0].unit_price == Decimal(4)
    assert parse.items[1].unit_price == Decimal("0.5")


@pytest.mark.parametrize(
    "legal_name", ["MERCADONA, S.A.", "Mercadona S.L.U.", "Mercadona SAU", "ООО Mercadona"]
)
def test_legal_suffixes_are_stripped_from_the_store_key(legal_name):
    assert normalize(raw_receipt(store=legal_name), **CONTEXT).store_key == "mercadona"


def test_cyrillic_store_key_and_ampersand():
    assert slug("ИП Пятёрочка") == "ип-пятерочка"
    assert normalize(raw_receipt(store="ИП Пятёрочка"), **CONTEXT).store_key == "пятерочка"
    assert slug("Fish & Chips") == "fish-and-chips"


def test_not_a_receipt_yields_a_bare_parse():
    parse = normalize(raw_receipt(is_receipt=False, items=[]), **CONTEXT)
    assert parse.is_receipt is False
    assert parse.items == ()
    assert parse.receipt_key is None
    assert parse.parser_version == PARSER_VERSION


def test_missing_purchase_time_uses_the_message_time():
    parse = normalize(raw_receipt(receipt=dict(number=None, purchased_at=None)), **CONTEXT)
    assert parse.purchased_at == CONTEXT["received_at"]
    assert parse.purchased_at.utcoffset().total_seconds() == 2 * 3600
    [issue] = [i for i in workflow_issues(parse) if i.field == "receipt.purchased_at"]
    assert issue.severity is IssueSeverity.MEDIUM


def test_unparseable_purchase_time_is_flagged_high_and_replaced():
    parse = normalize(raw_receipt(receipt=dict(number="1", purchased_at="yesterday")), **CONTEXT)
    assert parse.purchased_at == CONTEXT["received_at"]
    [issue] = [i for i in workflow_issues(parse) if i.field == "receipt.purchased_at"]
    assert issue.severity is IssueSeverity.HIGH


def test_sql_style_purchase_time_is_read_in_the_zone():
    parse = normalize(
        raw_receipt(receipt=dict(number="1", purchased_at="2026-10-12 9:05")), **CONTEXT
    )
    assert parse.purchased_at == datetime.fromisoformat("2026-10-12T07:05:00+00:00")


def test_date_far_from_the_message_and_not_fixable_is_kept_with_a_high_issue():
    parse = normalize(
        raw_receipt(receipt=dict(number="1", purchased_at="2026-01-02T10:00:00")), **CONTEXT
    )
    assert parse.purchased_at.date().isoformat() == "2026-01-02"
    [issue] = [i for i in workflow_issues(parse) if i.field == "receipt.purchased_at"]
    assert issue.issue_type == "ambiguous"
    assert issue.severity is IssueSeverity.HIGH


def test_missing_total_and_currency_and_items_are_flagged():
    parse = normalize(raw_receipt(items=[], total=None, currency=None), **CONTEXT)
    fields = {(i.field, i.severity) for i in workflow_issues(parse)}
    assert ("totals.total", IssueSeverity.HIGH) in fields
    assert ("currency", IssueSeverity.LOW) in fields
    assert ("items", IssueSeverity.HIGH) in fields
    assert parse.currency == "EUR"
    assert parse.receipt_key.endswith("|na")


def test_total_falls_back_to_the_amount_paid():
    raw = raw_receipt()
    raw["totals"]["total"] = None
    raw["payment"]["amount_paid"] = "3,50"
    assert normalize(raw, **CONTEXT).total == Decimal("3.5")


def test_card_digits_that_are_not_four_are_flagged_and_only_the_tail_is_kept():
    raw = raw_receipt()
    raw["payment"]["card_last4"] = "**12"
    parse = normalize(raw, **CONTEXT)
    assert parse.card_last4 == "12"
    [issue] = [i for i in workflow_issues(parse) if i.field == "payment.card_last4"]
    assert issue.severity is IssueSeverity.LOW


def test_full_card_number_is_cut_to_the_last_four_everywhere():
    raw = raw_receipt()
    raw["payment"]["card_last4"] = "4111 1111 1111 1234"
    parse = normalize(raw, **CONTEXT)
    assert parse.card_last4 == "1234"
    assert not [i for i in parse.issues if "4111" in i.message]


def test_line_math_off_by_more_than_two_cents_is_flagged():
    line = item("X", quantity=2, unit_price=Decimal("1.00"), line_total=Decimal("2.10"))
    parse = normalize(raw_receipt(items=[line], total=Decimal("2.10")), **CONTEXT)
    [issue] = [i for i in workflow_issues(parse) if i.issue_type == "totals_mismatch"]
    assert issue.field == "items.line_total"
    assert issue.item_name == "X"
    line["line_total"] = Decimal("2.02")
    ok = normalize(raw_receipt(items=[line], total=Decimal("2.02")), **CONTEXT)
    assert not workflow_issues(ok)


def test_lines_not_adding_up_to_the_total_are_flagged_high():
    parse = normalize(raw_receipt(items=[item("X")], total=5), **CONTEXT)
    [issue] = [i for i in workflow_issues(parse) if i.field == "totals.total"]
    assert issue.severity is IssueSeverity.HIGH
    assert "Lines add up to 1" in issue.message


def test_receipt_wide_discount_is_kept_and_counted():
    raw = raw_receipt(
        items=[
            item(
                "X",
            ),
            item("Y"),
        ],
        total=Decimal("1.50"),
    )
    raw["totals"]["discount_total"] = Decimal("0.50")
    parse = normalize(raw, **CONTEXT)
    assert parse.discount_total == Decimal("0.50")
    assert parse.subtotal == Decimal("2.00")
    assert parse.subtotal - parse.discount_total == parse.total
    assert not workflow_issues(parse)


def test_money_is_decimal_and_purchased_at_is_aware_in_the_zone():
    parse = normalize(raw_receipt(), **CONTEXT)
    assert isinstance(parse.total, Decimal)
    assert str(parse.purchased_at.tzinfo) == "Europe/Madrid"
    assert parse.raw_output["store"]["name"] == "Mercadona"


def test_naive_received_at_is_refused():
    with pytest.raises(InvalidReceiptData):
        normalize(raw_receipt(), **{**CONTEXT, "received_at": datetime(2026, 10, 12, 16, 0)})
