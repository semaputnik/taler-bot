"""The `Receipt` aggregate: one purchase with its photo, parse, items, issues and edits.

Percival & Gregory, *Architecture Patterns with Python*, ch. 1 and 7: `Receipt` is the root,
the only way to change its parts is through its methods, and they enforce the rules
(ADR-0002: one photo and at most one parse per receipt):

- the header is the parse with the user's edits applied on top;
- items are rebuilt from the parse whenever it is set or replaced, item edits applied;
- issues are the parse's issues plus one `merge` issue for every edit a re-parse disagrees
  with;
- a parse says it is not a receipt: status `not_receipt`, no items.

Parts that are stored carry an optional `id` (None until the repository inserts them), so
the repository can tell new rows from persisted ones. The photo and edits are append-only.
The repository reads two flags to decide what to rewrite and calls `mark_saved()`
afterwards: `parse_changed` (a parse was applied since load: rewrite the parse row, replace
the items and the issues) and `items_changed` (only an item edit: replace the items, leave
the issues and their resolutions alone).
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from src.domain.edits import ISSUE_FIELDS, ITEM_FIELDS, RECEIPT_FIELDS, Edit
from src.domain.enums import (
    EditTarget,
    IssueResolution,
    IssueSeverity,
    IssueSource,
    ReceiptStatus,
)
from src.domain.parse import Parse, ParsedIssue, ParsedItem, ParseOutcome
from src.exception import (
    InvalidEdit,
    InvalidIssueResolution,
    InvalidReceiptData,
    InvalidReceiptTransition,
    UnknownIssue,
)

__all__ = [
    "Edit",
    "Header",
    "Issue",
    "IssueCorrection",
    "Item",
    "Parse",
    "ParseOutcome",
    "ParsedIssue",
    "ParsedItem",
    "Photo",
    "Receipt",
]

MONEY_TOLERANCE = Decimal("0.02")
INTERRUPTED = "interrupted"
S = ReceiptStatus
_AWAITING_REVIEW = frozenset({IssueResolution.OPEN, IssueResolution.SKIPPED})
_SEVERITY_ORDER = {IssueSeverity.HIGH: 0, IssueSeverity.MEDIUM: 1, IssueSeverity.LOW: 2}
# Statuses that may receive a parse (a first one, or a re-parse).
_PARSEABLE = {S.PENDING, S.PARSING, S.PARSED, S.FAILED, S.NOT_RECEIPT}


@dataclass(kw_only=True)
class Photo:
    telegram_file_unique_id: str | None = None
    telegram_file_id: str | None = None
    telegram_message_id: int | None = None
    path: str | None = None  # relative to RECEIPTS_DIR; None until the bytes are stored
    mime_type: str | None = None
    size_bytes: int | None = None
    # Photos imported from n8n are kept in Google Drive until they are downloaded.
    drive_file_id: str | None = None
    drive_url: str | None = None
    received_at: datetime
    id: int | None = None

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            raise InvalidReceiptData("received_at must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class Header:
    """Receipt-level facts: the parse with the edits applied."""

    store_key: str | None = None
    purchased_at: datetime | None = None
    receipt_key: str | None = None
    receipt_number: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    discount_total: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal | None = None
    payment_method: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None


@dataclass(frozen=True, kw_only=True)
class Item(ParsedItem):
    """An item of the parse with edits applied. `ref` is its `product_key#occurrence`."""

    ref: str


@dataclass(kw_only=True)
class Issue:
    source: IssueSource
    issue_type: str
    severity: IssueSeverity
    field: str | None = None
    item_name: str | None = None
    message: str
    resolution: IssueResolution = IssueResolution.OPEN
    resolved_at: datetime | None = None
    id: int | None = None

    @classmethod
    def of(cls, parsed: ParsedIssue) -> Issue:
        return cls(
            source=parsed.source,
            issue_type=parsed.issue_type,
            severity=parsed.severity,
            field=parsed.field,
            item_name=parsed.item_name,
            message=parsed.message,
        )


class IssueCorrection(NamedTuple):
    """Where a typed value for an issue goes: the edit target, its item (if any) and field."""

    target: EditTarget
    item_ref: str | None
    field: str
    input_kind: str


@dataclass(kw_only=True)
class Receipt:
    user_id: int
    id: int | None = None
    status: ReceiptStatus = S.PENDING
    header: Header = field(default_factory=Header)
    photo: Photo
    parse: Parse | None = None
    items: list[Item] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)
    duplicate_of_id: int | None = None
    deleted_at: datetime | None = None
    error_message: str | None = None
    source_ref: str | None = None  # "n8n:<id>" on imported receipts, so the import can rerun

    # Change tracking for the repository (see module docstring); reset by `mark_saved()`.
    parse_changed: bool = field(default=False, init=False, repr=False)
    items_changed: bool = field(default=False, init=False, repr=False)

    @classmethod
    def start(cls, user_id: int, photo: Photo) -> Receipt:
        return cls(user_id=user_id, photo=photo)

    # --- parse -------------------------------------------------------------------------

    def apply_parse(self, parse: Parse, same_key_as: int | None = None) -> ParseOutcome:
        """Set or replace the parse and rebuild header, items and issues from it.

        `same_key_as` is the id of another parsed receipt of the user with this parse's receipt
        key (the service looks it up). A parse that is a receipt then makes this one a
        `duplicate` of it: it keeps its parse but never collides with the parsed key.
        """
        self._ensure_open()
        if self.status not in _PARSEABLE:
            raise InvalidReceiptTransition(f"cannot parse a {self.status} receipt")
        previous = _used_keys(self.parse)
        carried = _resolutions_of(self.issues)
        self.parse = parse
        self.header, self.items = self._with_edits(parse)
        self.issues = [_carry(Issue.of(i), carried) for i in parse.issues]
        if parse.is_receipt:
            self.issues += self._conflicts(parse)  # regenerated, never carried
            self.status = S.PARSED
            if same_key_as is not None and same_key_as != self.id:
                self.mark_duplicate(same_key_as)
        else:
            self.status = S.NOT_RECEIPT
        self.error_message = None
        self.parse_changed = True
        used = _used_keys(parse)
        return ParseOutcome(product_keys_used=used, product_keys_released=previous - used)

    def top_issues(self, limit: int = 5) -> list[Issue]:
        """The most severe issues, high first, in parse order within a severity."""
        return sorted(self.issues, key=lambda i: _SEVERITY_ORDER[i.severity])[:limit]

    def reviewable_issues(self) -> list[Issue]:
        """Issues of severity high or medium still waiting for the user, high first, in parse
        order within each. A skipped issue waits for a later walk, so it stays in the list."""
        waiting = [
            i
            for i in self.issues
            if i.resolution in _AWAITING_REVIEW and i.severity is not IssueSeverity.LOW
        ]
        return sorted(waiting, key=lambda i: _SEVERITY_ORDER[i.severity])

    def item_of(self, issue: Issue) -> Item | None:
        """The item an `items.*` issue is about: the first whose printed name is the issue's."""
        if issue.item_name is None or not (issue.field or "").startswith("items."):
            return None
        return next((i for i in self.items if i.printed_name == issue.item_name), None)

    def issue_correction(self, issue: Issue) -> IssueCorrection | None:
        """Which edit a typed value for this issue makes; None when it cannot be fixed by typing."""
        mapped = ISSUE_FIELDS.get(issue.field or "")
        if mapped is None:
            return None
        if mapped.target is EditTarget.RECEIPT:
            return IssueCorrection(mapped.target, None, mapped.field, mapped.input_kind)
        item = self.item_of(issue)
        if item is None:
            return None
        return IssueCorrection(mapped.target, item.ref, mapped.field, mapped.input_kind)

    def current_value(self, issue: Issue) -> Any:
        """What the header or item holds now for the issue's field; None if not correctable."""
        correction = self.issue_correction(issue)
        if correction is None:
            return None
        if correction.target is EditTarget.RECEIPT:
            return getattr(self.header, correction.field)
        item = next(i for i in self.items if i.ref == correction.item_ref)
        return getattr(item, correction.field)

    # --- edits and issues --------------------------------------------------------------

    def record_edit(self, edit: Edit) -> None:
        """Keep the user's value on top of every parse, now and after any re-parse."""
        self._ensure_open()
        if self.parse is None or not self.parse.is_receipt:
            raise InvalidReceiptTransition("only a parsed receipt can be edited")
        if edit.target is EditTarget.ITEM and all(i.ref != edit.item_ref for i in self.items):
            raise InvalidEdit(f"the receipt has no item {edit.item_ref}")
        self.edits.append(edit)
        self.header, self.items = self._with_edits(self.parse)
        if edit.target is EditTarget.ITEM:
            self.items_changed = True

    def resolve_issue(
        self, issue_id: int, resolution: IssueResolution, at: datetime | None = None
    ) -> None:
        self._ensure_open()
        if resolution is IssueResolution.OPEN:
            raise InvalidIssueResolution("an issue is resolved as confirmed, corrected or skipped")
        issue = next((i for i in self.issues if i.id == issue_id), None)
        if issue is None:
            raise UnknownIssue(issue_id)
        issue.resolution = resolution
        issue.resolved_at = at or datetime.now(UTC)

    def correct_issue(self, issue_id: int, value: Any, at: datetime | None = None) -> None:
        """Answer an open issue with the right value: record the edit, resolve it `corrected`."""
        self._ensure_open()
        issue = next((i for i in self.issues if i.id == issue_id), None)
        if issue is None:
            raise UnknownIssue(issue_id)
        if issue.resolution not in _AWAITING_REVIEW:
            raise InvalidIssueResolution(f"issue {issue_id} is already {issue.resolution}")
        correction = self.issue_correction(issue)
        if correction is None:
            raise InvalidEdit(f"issue {issue_id} ({issue.field}) cannot be corrected by a value")
        self.record_edit(
            Edit(
                target=correction.target,
                item_ref=correction.item_ref,
                field=correction.field,
                value=value,
                issue_id=issue_id,
            )
        )
        self.resolve_issue(issue_id, IssueResolution.CORRECTED, at)

    def edit_header_field(self, field: str, value: Any, at: datetime | None = None) -> None:
        """Edit a header field; the edit answers every awaiting issue that points at it.

        One edit is recorded, tied to the first such issue; the other issues on the same field
        are resolved `corrected` by it. With no such issue it is a plain receipt edit.
        Clearing (value None) is an edit too.
        """
        self._ensure_open()
        awaiting = [
            i
            for i in self.issues
            if i.resolution in _AWAITING_REVIEW and self._targets_header_field(i, field)
        ]
        if not awaiting:
            self.record_edit(Edit(target=EditTarget.RECEIPT, field=field, value=value))
            return
        first, *rest = awaiting
        self.correct_issue(first.id, value, at)
        for issue in rest:
            self.resolve_issue(issue.id, IssueResolution.CORRECTED, at)

    def _targets_header_field(self, issue: Issue, field: str) -> bool:
        correction = self.issue_correction(issue)
        return (
            correction is not None
            and correction.target is EditTarget.RECEIPT
            and correction.field == field
        )

    # --- status transitions ------------------------------------------------------------

    def mark_parsing(self) -> None:
        """The photo is being read: a first parse or a re-parse has started.

        Any receipt that can take a parse may be read again, except a duplicate (it would
        compete with the original for the key) and one already being read.
        """
        self._transition({S.PENDING, S.FAILED, S.PARSED, S.NOT_RECEIPT}, S.PARSING)

    def mark_duplicate(self, of_receipt_id: int) -> None:
        """Another parsed receipt of the user has the same receipt key."""
        if self.id is not None and of_receipt_id == self.id:
            raise InvalidReceiptTransition("a receipt cannot be a duplicate of itself")
        self._transition({S.PARSED}, S.DUPLICATE)
        self.duplicate_of_id = of_receipt_id

    def mark_failed(self, reason: str) -> None:
        """A read did not succeed; the reason is kept in `error_message`.

        A receipt that was being read and already has a parse (a re-parse) goes back to what
        that parse says it is: `parsed` or `not_receipt`, with parse, header, items, issues and
        resolutions untouched. Without a parse it is `failed`. This is decided by data, not by
        a remembered status, because the failure is recorded in a fresh Unit of Work.
        """
        self._transition({S.PENDING, S.PARSING, S.FAILED}, self._status_after_failed_read())
        self.error_message = reason

    def recover_interrupted(self) -> None:
        """The bot stopped while this receipt was being read: same as a failed read."""
        if self.status is not S.PARSING:
            raise InvalidReceiptTransition(f"a {self.status} receipt was not interrupted")
        self.mark_failed(INTERRUPTED)

    @property
    def can_reparse(self) -> bool:
        """Whether the photo can be read again: a settled reading (or failure), not deleted."""
        return self.deleted_at is None and self.status in {S.PARSED, S.FAILED, S.NOT_RECEIPT}

    @property
    def backs_expense(self) -> bool:
        """Whether the receipt is a purchase the user made: read and a receipt, not a repeat of
        another one, not deleted. Only such a receipt has an expense (ADR-0003)."""
        return self.deleted_at is None and self.status is S.PARSED

    @property
    def parser_version(self) -> str | None:
        return self.parse.parser_version if self.parse is not None else None

    def mark_not_receipt(self) -> None:
        self._transition({S.PENDING, S.PARSING, S.FAILED}, S.NOT_RECEIPT)
        self.issues = []
        self._clear_items()

    def soft_delete(self, at: datetime | None = None) -> None:
        if self.deleted_at is not None:
            raise InvalidReceiptTransition("the receipt is already deleted")
        if self.status is S.PARSING:
            raise InvalidReceiptTransition("the receipt is being read; wait for the result")
        self.deleted_at = at or datetime.now(UTC)

    # --- for the repository ------------------------------------------------------------

    def mark_saved(self) -> None:
        self.parse_changed = False
        self.items_changed = False

    # --- internals ---------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self.deleted_at is not None:
            raise InvalidReceiptTransition("the receipt is deleted")

    def _transition(self, allowed: set[ReceiptStatus], new: ReceiptStatus) -> None:
        self._ensure_open()
        if self.status not in allowed:
            raise InvalidReceiptTransition(f"cannot go from {self.status} to {new}")
        self.status = new
        if new is not S.FAILED:
            self.error_message = None

    def _status_after_failed_read(self) -> ReceiptStatus:
        if self.status is S.PARSING and self.parse is not None:
            return S.PARSED if self.parse.is_receipt else S.NOT_RECEIPT
        return S.FAILED

    def _clear_items(self) -> None:
        self.items = []
        self.items_changed = True

    def _effective_edits(self) -> dict[tuple[EditTarget, str | None, str], Edit]:
        """The last edit of every (target, item, field): later edits replace earlier ones."""
        return {(e.target, e.item_ref, e.field): e for e in self.edits}

    def _with_edits(self, parse: Parse) -> tuple[Header, list[Item]]:
        header = Header(**{name: getattr(parse, name) for name in Header.__dataclass_fields__})
        if not parse.is_receipt:
            return header, []
        items = _items_of(parse)
        for (target, item_ref, name), edit in self._effective_edits().items():
            if target is EditTarget.RECEIPT:
                header = replace(header, **{name: edit.coerced()})
            else:
                items = [
                    replace(i, **{name: edit.coerced()}) if i.ref == item_ref else i for i in items
                ]
        return header, items

    def _conflicts(self, parse: Parse) -> list[Issue]:
        """One `merge` issue per edit the parse reads differently."""
        parsed_items = {i.ref: i for i in _items_of(parse)}
        found: list[Issue] = []
        for (target, item_ref, name), edit in self._effective_edits().items():
            mine = edit.coerced()
            if target is EditTarget.RECEIPT:
                theirs, label, item_name = getattr(parse, name), name, None
            else:
                item = parsed_items.get(item_ref or "")
                if item is None:
                    found.append(
                        _conflict(
                            f"items.{name}",
                            item_ref,
                            f"You edited {item_ref}, but the new reading has no "
                            "such item; the edit is ignored.",
                        )
                    )
                    continue
                theirs, label, item_name = getattr(item, name), f"items.{name}", item.printed_name
            if not _same(target, name, theirs, mine):
                found.append(
                    _conflict(
                        label,
                        item_name,
                        f"You set {name} to {mine}, the new reading has "
                        f"{theirs}; your value is kept.",
                    )
                )
        return found


_IssueKey = tuple[IssueSource, str, str | None, str | None, str]


def _issue_key(issue: Issue) -> _IssueKey:
    return (issue.source, issue.issue_type, issue.field, issue.item_name, issue.message)


def _resolutions_of(issues: list[Issue]) -> dict[_IssueKey, list[Issue]]:
    """The previous issues by identity, in order, so each can be carried to one new issue."""
    found: dict[_IssueKey, list[Issue]] = {}
    for issue in issues:
        found.setdefault(_issue_key(issue), []).append(issue)
    return found


def _carry(new: Issue, previous: dict[_IssueKey, list[Issue]]) -> Issue:
    """Copy the user's resolution from the first unused equal previous issue, if any."""
    candidates = previous.get(_issue_key(new))
    if candidates:
        old = candidates.pop(0)
        new.resolution, new.resolved_at = old.resolution, old.resolved_at
    return new


def _used_keys(parse: Parse | None) -> frozenset[str]:
    return parse.product_keys if parse is not None and parse.is_receipt else frozenset()


def _same(target: EditTarget, name: str, parsed: object, edited: object) -> bool:
    """Equal, with the 0.02 tolerance CLAUDE.md prescribes for comparing money."""
    kind = (ITEM_FIELDS if target is EditTarget.ITEM else RECEIPT_FIELDS)[name][0]
    if kind == "money" and isinstance(parsed, Decimal) and isinstance(edited, Decimal):
        return abs(parsed - edited) <= MONEY_TOLERANCE
    return parsed == edited


def _items_of(parse: Parse) -> list[Item]:
    seen: dict[str, int] = {}
    items = []
    for parsed in parse.items:
        seen[parsed.product_key] = seen.get(parsed.product_key, 0) + 1
        ref = f"{parsed.product_key}#{seen[parsed.product_key]}"
        items.append(
            Item(ref=ref, **{f: getattr(parsed, f) for f in ParsedItem.__dataclass_fields__})
        )
    return items


def _conflict(label: str, item_name: str | None, message: str) -> Issue:
    return Issue(
        source=IssueSource.MERGE,
        issue_type="edit_conflict",
        severity=IssueSeverity.MEDIUM,
        field=label,
        item_name=item_name,
        message=message,
    )
