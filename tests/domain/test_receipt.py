from datetime import datetime
from decimal import Decimal

import pytest

from src.domain.enums import EditTarget, IssueResolution, IssueSource, ReceiptStatus
from src.domain.receipt import Edit, Issue, ParsedIssue, Photo, Receipt
from src.exception import (
    InvalidEdit,
    InvalidIssueResolution,
    InvalidReceiptData,
    InvalidReceiptTransition,
    UnknownIssue,
)
from tests.domain.builders import WHEN, parse, photo, product


def started() -> Receipt:
    return Receipt.start(user_id=1, photo=photo())


def test_a_started_receipt_is_pending_with_its_photo_and_no_parse():
    receipt = started()
    assert receipt.status is ReceiptStatus.PENDING
    assert receipt.photo.telegram_file_unique_id == "u1"
    assert receipt.parse is None


def test_applying_a_parse_fills_header_items_and_status():
    receipt = started()
    receipt.apply_parse(parse(product("mercadona::leche"), product("mercadona::pan", "0.80")))
    assert receipt.status is ReceiptStatus.PARSED
    assert receipt.header.total == Decimal("47.50")
    assert receipt.header.store_key == "mercadona"
    assert [i.ref for i in receipt.items] == ["mercadona::leche#1", "mercadona::pan#1"]


def total_edit(value: str = "47.85") -> Edit:
    return Edit(target=EditTarget.RECEIPT, field="total", value=value)


def merge_issues(receipt: Receipt) -> list[Issue]:
    return [i for i in receipt.issues if i.source is IssueSource.MERGE]


# --- edits survive re-parses -------------------------------------------------------------


def test_an_edit_wins_over_a_second_parse_and_a_merge_issue_notes_the_disagreement():
    receipt = started()
    receipt.apply_parse(parse(id=1))
    receipt.record_edit(total_edit("47.85"))
    assert receipt.header.total == Decimal("47.85")
    assert merge_issues(receipt) == []  # correcting a value is not a disagreement yet

    receipt.apply_parse(parse(id=2, total=Decimal("47.60")))

    assert receipt.header.total == Decimal("47.85")
    [issue] = merge_issues(receipt)
    assert issue.field == "total"
    assert "47.85" in issue.message and "47.60" in issue.message


def test_no_merge_issue_when_the_new_parse_agrees_with_the_edit():
    receipt = started()
    receipt.apply_parse(parse(id=1))
    receipt.record_edit(total_edit("47.85"))
    receipt.apply_parse(parse(id=2, total=Decimal("47.850")))
    assert merge_issues(receipt) == []


def test_the_last_edit_of_a_field_wins():
    receipt = started()
    receipt.apply_parse(parse(id=1))
    receipt.record_edit(total_edit("10"))
    receipt.record_edit(total_edit("12"))
    assert receipt.header.total == Decimal("12")
    assert len(receipt.edits) == 2


def test_an_item_edit_is_keyed_by_product_key_and_occurrence_and_survives_a_reparse():
    leche = "mercadona::leche"
    receipt = started()
    receipt.apply_parse(parse(product(leche), product(leche, "1.30"), id=1))
    receipt.record_edit(
        Edit(target=EditTarget.ITEM, item_ref=f"{leche}#2", field="quantity", value="3")
    )
    assert [i.quantity for i in receipt.items] == [Decimal(1), Decimal(3)]

    receipt.apply_parse(parse(product(leche), product(leche, "1.30"), id=2))

    assert [i.quantity for i in receipt.items] == [Decimal(1), Decimal(3)]
    [issue] = merge_issues(receipt)
    assert issue.field == "items.quantity"


def test_an_item_edit_for_an_item_the_new_parse_lacks_raises_a_merge_issue():
    receipt = started()
    receipt.apply_parse(parse(product("mercadona::leche"), id=1))
    receipt.record_edit(
        Edit(target=EditTarget.ITEM, item_ref="mercadona::leche#1", field="line_total", value="2")
    )
    receipt.apply_parse(parse(product("mercadona::pan"), id=2))
    assert [i.ref for i in receipt.items] == ["mercadona::pan#1"]
    assert len(merge_issues(receipt)) == 1


@pytest.mark.parametrize(
    "edit",
    [
        dict(target=EditTarget.RECEIPT, field="nope", value="1"),
        dict(target=EditTarget.RECEIPT, field="total", value="abc"),
        dict(target=EditTarget.RECEIPT, field="card_last4", value="12"),
        dict(target=EditTarget.RECEIPT, field="total", value="1", item_ref="x#1"),
        dict(target=EditTarget.ITEM, field="quantity", value="1"),
        dict(target=EditTarget.ITEM, field="quantity", value=None, item_ref="x#1"),
    ],
)
def test_an_invalid_edit_is_rejected(edit):
    with pytest.raises(InvalidEdit):
        Edit(**edit)


# --- guards -----------------------------------------------------------------------------


def test_a_duplicate_receipt_refuses_apply_parse():
    receipt = started()
    receipt.apply_parse(parse())
    receipt.mark_duplicate(7)
    with pytest.raises(InvalidReceiptTransition):
        receipt.apply_parse(parse())


def test_soft_delete_sets_deleted_at_and_freezes_the_receipt():
    receipt = started()
    receipt.soft_delete(at=WHEN)
    assert receipt.deleted_at == WHEN
    with pytest.raises(InvalidReceiptTransition):
        receipt.apply_parse(parse())
    with pytest.raises(InvalidReceiptTransition):
        receipt.soft_delete()
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_failed("x")
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_not_receipt()
    with pytest.raises(InvalidReceiptTransition):
        receipt.resolve_issue(1, IssueResolution.SKIPPED)


def test_a_deleted_parsed_receipt_refuses_edits_and_duplicate_marking():
    receipt = started()
    receipt.apply_parse(parse())
    receipt.soft_delete(at=WHEN)
    with pytest.raises(InvalidReceiptTransition):
        receipt.record_edit(total_edit())
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_duplicate(7)


def test_failure_transitions_are_guarded():
    receipt = started()
    receipt.mark_failed("timeout")
    assert (receipt.status, receipt.error_message) == (ReceiptStatus.FAILED, "timeout")
    receipt.apply_parse(parse(id=1))
    assert receipt.error_message is None
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_failed("late")
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_not_receipt()


def test_mark_not_receipt_clears_the_items():
    receipt = started()
    receipt.mark_not_receipt()
    assert receipt.status is ReceiptStatus.NOT_RECEIPT
    assert receipt.items == []


# --- photo -----------------------------------------------------------------------------


def test_a_photo_must_have_a_timezone_aware_time():
    with pytest.raises(InvalidReceiptData):
        Photo(telegram_file_unique_id="x", received_at=datetime(2026, 1, 1))


# --- parse outcome ----------------------------------------------------------------------


def test_parse_outcome_lists_used_and_released_product_keys_across_two_parses():
    receipt = started()
    first = receipt.apply_parse(parse(product("m::leche"), product("m::pan"), id=1))
    assert first.product_keys_used == {"m::leche", "m::pan"}
    assert first.product_keys_released == frozenset()

    second = receipt.apply_parse(parse(product("m::leche"), product("m::miel"), id=2))
    assert second.product_keys_used == {"m::leche", "m::miel"}
    assert second.product_keys_released == {"m::pan"}


# --- issues -----------------------------------------------------------------------------


def with_issue() -> Receipt:
    receipt = started()
    receipt.apply_parse(
        parse(id=1, issues=(ParsedIssue(issue_type="ambiguous", field="total", message="?"),))
    )
    receipt.issues[0].id = 10
    return receipt


def test_resolve_issue_marks_an_active_issue():
    receipt = with_issue()
    receipt.resolve_issue(10, IssueResolution.CONFIRMED, at=WHEN)
    assert receipt.issues[0].resolution is IssueResolution.CONFIRMED
    assert receipt.issues[0].resolved_at == WHEN


def test_resolve_issue_refuses_unknown_and_no_longer_active_issues():
    receipt = with_issue()
    with pytest.raises(UnknownIssue):
        receipt.resolve_issue(99, IssueResolution.SKIPPED)
    receipt.apply_parse(parse(id=2))  # the old parse's issues are no longer active
    with pytest.raises(UnknownIssue):
        receipt.resolve_issue(10, IssueResolution.SKIPPED)


def test_an_issue_cannot_be_resolved_as_open():
    with pytest.raises(InvalidIssueResolution):
        with_issue().resolve_issue(10, IssueResolution.OPEN)


def test_issues_are_the_parses_and_a_reparse_replaces_them():
    receipt = with_issue()
    receipt.apply_parse(parse(id=2))
    assert receipt.issues == []


# --- not a receipt ----------------------------------------------------------------------


def test_a_parse_that_is_not_a_receipt_sets_not_receipt_and_no_items():
    receipt = started()
    receipt.apply_parse(parse(id=1))
    outcome = receipt.apply_parse(parse(id=2, is_receipt=False, items=()))
    assert receipt.status is ReceiptStatus.NOT_RECEIPT
    assert receipt.items == []
    assert outcome.product_keys_used == frozenset()
    assert outcome.product_keys_released == {"mercadona::leche"}


# --- change tracking --------------------------------------------------------------------


def test_the_receipt_reports_what_the_repository_must_rewrite():
    receipt = started()
    assert not receipt.parse_changed
    receipt.apply_parse(parse(id=1))
    assert receipt.parse_changed  # implies: replace the parse row, items and issues
    receipt.mark_saved()
    assert not receipt.parse_changed and not receipt.items_changed

    receipt.record_edit(total_edit())  # header only: items and issues stay as stored
    assert not receipt.parse_changed and not receipt.items_changed

    receipt.record_edit(
        Edit(target=EditTarget.ITEM, item_ref="mercadona::leche#1", field="unit", value="kg")
    )
    assert receipt.items_changed and not receipt.parse_changed


def test_a_second_parse_replaces_the_first_and_nothing_is_kept_of_it():
    receipt = started()
    receipt.apply_parse(parse(product("m::leche"), id=1))
    second = parse(product("m::pan"), id=2)
    receipt.apply_parse(second)
    assert receipt.parse is second
    assert [i.ref for i in receipt.items] == ["m::pan#1"]


# --- review follow-ups -------------------------------------------------------------------


def test_an_item_edit_for_an_unknown_item_is_rejected():
    receipt = started()
    receipt.apply_parse(parse(id=1))
    with pytest.raises(InvalidEdit):
        receipt.record_edit(
            Edit(target=EditTarget.ITEM, item_ref="mercadona::nope#1", field="unit", value="kg")
        )
    assert receipt.edits == []


def test_a_non_finite_number_is_not_a_valid_edit():
    with pytest.raises(InvalidEdit):
        total_edit("NaN")


def test_money_within_two_cents_is_not_a_disagreement():
    receipt = started()
    receipt.apply_parse(parse(id=1))
    receipt.record_edit(total_edit("47.51"))
    receipt.apply_parse(parse(id=2, total=Decimal("47.52")))
    assert merge_issues(receipt) == []
    receipt.apply_parse(parse(id=3, total=Decimal("47.60")))
    assert len(merge_issues(receipt)) == 1


def test_keys_of_a_parse_that_was_not_a_receipt_are_not_released():
    receipt = started()
    receipt.apply_parse(parse(id=1, is_receipt=False))
    outcome = receipt.apply_parse(parse(id=2))
    assert outcome.product_keys_released == frozenset()


# --- duplicates -------------------------------------------------------------------------


def test_a_parsed_receipt_can_be_marked_a_duplicate_of_another():
    receipt = started()
    receipt.apply_parse(parse())
    receipt.mark_duplicate(7)
    assert (receipt.status, receipt.duplicate_of_id) == (ReceiptStatus.DUPLICATE, 7)


@pytest.mark.parametrize("setup", ["pending", "failed", "not_receipt", "duplicate"])
def test_mark_duplicate_is_only_allowed_from_parsed(setup):
    receipt = started()
    if setup == "failed":
        receipt.mark_failed("x")
    elif setup == "not_receipt":
        receipt.mark_not_receipt()
    elif setup == "duplicate":
        receipt.apply_parse(parse())
        receipt.mark_duplicate(7)
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_duplicate(8)
    assert receipt.duplicate_of_id == (7 if setup == "duplicate" else None)


def test_a_receipt_cannot_be_a_duplicate_of_itself():
    receipt = started()
    receipt.id = 5
    receipt.apply_parse(parse())
    with pytest.raises(InvalidReceiptTransition):
        receipt.mark_duplicate(5)


# --- apply_parse from every parseable status --------------------------------------------


@pytest.mark.parametrize("setup", ["pending", "parsing", "parsed", "failed", "not_receipt"])
def test_apply_parse_is_allowed_from_every_status_but_duplicate(setup):
    receipt = started()
    if setup == "parsing":
        receipt.status = ReceiptStatus.PARSING
    elif setup == "parsed":
        receipt.apply_parse(parse())
    elif setup == "failed":
        receipt.mark_failed("x")
    elif setup == "not_receipt":
        receipt.mark_not_receipt()
    receipt.apply_parse(parse())
    assert receipt.status is ReceiptStatus.PARSED
