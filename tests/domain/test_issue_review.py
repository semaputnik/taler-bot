"""Which issues a user reviews, which of them a typed value can fix, and how it is applied."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.edits import ISSUE_FIELDS, Edit
from src.domain.enums import EditTarget, IssueResolution, IssueSeverity, IssueSource
from src.domain.receipt import Issue, ParsedIssue, Receipt
from src.exception import (
    InvalidEdit,
    InvalidIssueResolution,
    InvalidReceiptTransition,
    UnknownIssue,
)
from tests.domain.builders import WHEN, parse, photo, product

HIGH, MEDIUM, LOW = IssueSeverity.HIGH, IssueSeverity.MEDIUM, IssueSeverity.LOW


def issue(severity=MEDIUM, field=None, item_name=None, message="?", **fields) -> ParsedIssue:
    return ParsedIssue(
        severity=severity, field=field, item_name=item_name, message=message, **fields
    )


def receipt_with(*issues: ParsedIssue, items=None) -> Receipt:
    receipt = Receipt.start(user_id=1, photo=photo())
    receipt.apply_parse(parse(*(items or ()), id=1, issues=issues))
    for number, each in enumerate(receipt.issues, start=10):
        each.id = number  # as if stored
    return receipt


def test_reviewable_issues_are_waiting_high_and_medium_high_first_in_parse_order():
    receipt = receipt_with(
        issue(LOW, message="low-0"),
        issue(MEDIUM, message="medium-1"),
        issue(HIGH, message="high-2"),
        issue(MEDIUM, message="medium-3"),
        issue(HIGH, message="high-4"),
        issue(MEDIUM, message="resolved-5"),
        issue(MEDIUM, message="skipped-6"),
    )
    receipt.resolve_issue(15, IssueResolution.CONFIRMED)
    receipt.resolve_issue(16, IssueResolution.SKIPPED)  # waits for a later walk
    assert [i.message for i in receipt.reviewable_issues()] == [
        "high-2",
        "high-4",
        "medium-1",
        "medium-3",
        "skipped-6",
    ]


def test_merge_issues_are_reviewable_like_the_others():
    receipt = receipt_with()
    receipt.record_edit(_total("40.00"))
    receipt.apply_parse(parse(id=2))
    assert [i.source for i in receipt.reviewable_issues()] == [IssueSource.MERGE]


def test_top_issues_keep_their_behaviour():
    receipt = receipt_with(issue(LOW, message="a"), issue(HIGH, message="b"))
    assert [i.message for i in receipt.top_issues()] == ["b", "a"]


def _total(value: str):
    return Edit(target=EditTarget.RECEIPT, field="total", value=value)


RECEIPT_MAPPING = {
    "receipt.purchased_at": ("purchased_at", "datetime"),
    "receipt.number": ("receipt_number", "text"),
    "currency": ("currency", "currency"),
    "totals.total": ("total", "money"),
    "totals.subtotal": ("subtotal", "money"),
    "totals.discount_total": ("discount_total", "money"),
    "totals.tax_total": ("tax_total", "money"),
    "payment.method": ("payment_method", "text"),
    "payment.card_last4": ("card_last4", "last4"),
}
ITEM_MAPPING = {
    "items.quantity": ("quantity", "number"),
    "items.unit_price": ("unit_price", "number"),
    "items.reference_price": ("reference_price", "number"),
    "items.discount": ("discount", "money"),
    "items.line_total": ("line_total", "money"),
    "items.vat_rate": ("vat_rate", "number"),
}


def test_the_mapping_holds_exactly_the_agreed_fields():
    assert set(ISSUE_FIELDS) == set(RECEIPT_MAPPING) | set(ITEM_MAPPING)


@pytest.mark.parametrize(("issue_field", "expected"), RECEIPT_MAPPING.items())
def test_a_receipt_issue_field_maps_to_its_edit_field(issue_field, expected):
    receipt = receipt_with(issue(field=issue_field))
    assert receipt.issue_correction(receipt.issues[0]) == (
        EditTarget.RECEIPT,
        None,
        expected[0],
        expected[1],
    )


@pytest.mark.parametrize(("issue_field", "expected"), ITEM_MAPPING.items())
def test_an_item_issue_field_maps_to_the_matching_items_field(issue_field, expected):
    receipt = receipt_with(issue(field=issue_field, item_name="LECHE"), items=[product()])
    assert receipt.issue_correction(receipt.issues[0]) == (
        EditTarget.ITEM,
        "mercadona::leche#1",
        expected[0],
        expected[1],
    )


@pytest.mark.parametrize(
    "other",
    [
        None,
        "items.name_raw",
        "items.name_normalized",
        "store.address",
        "store.tax_id",
        "receipt.cashier",
        "receipt.register",
        "payment.auth_code",
        "loyalty.savings",
        "items",
        "total",
    ],
)
def test_any_other_field_is_not_correctable(other):
    receipt = receipt_with(issue(field=other, item_name="LECHE"), items=[product()])
    assert receipt.issue_correction(receipt.issues[0]) is None


def test_the_item_is_the_first_whose_printed_name_equals_the_issues_item_name():
    first, second = product("mercadona::leche"), product("mercadona::leche", total="1.30")
    receipt = receipt_with(
        issue(field="items.line_total", item_name="LECHE"), items=[first, second]
    )
    correction = receipt.issue_correction(receipt.issues[0])
    assert correction is not None
    assert correction.item_ref == "mercadona::leche#1"


def test_an_item_issue_without_a_matching_item_is_not_correctable():
    receipt = receipt_with(
        issue(field="items.line_total", item_name="PAN"),
        issue(field="items.line_total"),
        items=[product()],
    )
    assert [receipt.issue_correction(i) for i in receipt.issues] == [None, None]


def test_item_of_finds_the_item_of_any_items_issue():
    receipt = receipt_with(issue(field="items.name_raw", item_name="LECHE"), items=[product()])
    item = receipt.item_of(receipt.issues[0])
    assert item is not None
    assert item.readable_name == "Leche"
    assert receipt.item_of(Issue.of(issue(field="store.address", item_name="LECHE"))) is None


def test_correct_issue_records_an_edit_with_the_issue_id_and_resolves_it():
    receipt = receipt_with(issue(field="totals.total"))
    receipt.correct_issue(10, "48.10", at=WHEN)

    assert receipt.header.total == Decimal("48.10")
    [edit] = receipt.edits
    assert (edit.target, edit.field, edit.issue_id, edit.item_ref) == (
        EditTarget.RECEIPT,
        "total",
        10,
        None,
    )
    assert receipt.issues[0].resolution is IssueResolution.CORRECTED
    assert receipt.issues[0].resolved_at == WHEN


def test_correct_issue_applies_an_item_value_to_the_item():
    receipt = receipt_with(
        issue(field="items.line_total", item_name="LECHE"), items=[product(total="1.20")]
    )
    receipt.correct_issue(10, Decimal("1.50"))

    assert receipt.items[0].line_total == Decimal("1.50")
    assert receipt.edits[0].item_ref == "mercadona::leche#1"
    assert receipt.items_changed


def test_correct_issue_takes_a_datetime():
    receipt = receipt_with(issue(field="receipt.purchased_at"))
    when = datetime(2026, 10, 13, 9, 5, tzinfo=UTC)
    receipt.correct_issue(10, when)
    assert receipt.header.purchased_at == when


def test_a_bad_value_raises_and_leaves_the_issue_open():
    receipt = receipt_with(issue(field="payment.card_last4"))
    with pytest.raises(InvalidEdit):
        receipt.correct_issue(10, "12")
    assert receipt.edits == []
    assert receipt.issues[0].resolution is IssueResolution.OPEN


def test_a_non_editable_issue_cannot_be_corrected():
    receipt = receipt_with(issue(field="store.address"))
    with pytest.raises(InvalidEdit):
        receipt.correct_issue(10, "x")
    assert receipt.issues[0].resolution is IssueResolution.OPEN


def test_an_unknown_issue_cannot_be_corrected():
    with pytest.raises(UnknownIssue):
        receipt_with(issue(field="totals.total")).correct_issue(99, "1")


@pytest.mark.parametrize("first", [IssueResolution.CONFIRMED, IssueResolution.CORRECTED])
def test_a_resolved_issue_cannot_be_corrected(first):
    receipt = receipt_with(issue(field="totals.total"))
    receipt.resolve_issue(10, first)
    with pytest.raises(InvalidIssueResolution):
        receipt.correct_issue(10, "1")
    assert receipt.edits == []


def test_a_skipped_issue_can_still_be_corrected_later():
    receipt = receipt_with(issue(field="totals.total"))
    receipt.resolve_issue(10, IssueResolution.SKIPPED)
    receipt.correct_issue(10, "1")
    assert receipt.issues[0].resolution is IssueResolution.CORRECTED


def test_a_deleted_receipt_cannot_be_corrected():
    receipt = receipt_with(issue(field="totals.total"))
    receipt.soft_delete()
    with pytest.raises(InvalidReceiptTransition):
        receipt.correct_issue(10, "1")


def test_current_value_is_the_header_or_item_value_with_edits_applied():
    receipt = receipt_with(
        issue(field="totals.total"),
        issue(field="items.line_total", item_name="LECHE"),
        issue(field="store.address"),
        items=[product(total="1.20")],
    )
    total, line, other = receipt.issues
    assert receipt.current_value(total) == Decimal("47.50")
    assert receipt.current_value(line) == Decimal("1.20")
    assert receipt.current_value(other) is None
    receipt.correct_issue(10, "50")
    assert receipt.current_value(total) == Decimal("50")
