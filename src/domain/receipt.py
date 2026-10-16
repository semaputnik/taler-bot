"""The `Receipt` aggregate: one purchase with its photos, parses, items, issues and edits.

Percival & Gregory, *Architecture Patterns with Python*, ch. 1 and 7: `Receipt` is the root,
the only way to change its parts is through its methods, and they enforce the rules:

- the header is the current parse with the user's edits applied on top;
- items are rebuilt from the current parse whenever it changes, item edits applied;
- active issues are the current parse's issues plus one `merge` issue for every edit the
  parse disagrees with;
- a parse says it is not a receipt: status `not_receipt`, no items.

Parts that are stored carry an optional `id` (None until the repository inserts them), so
the repository can tell new rows from persisted ones. Photos, parses and edits are
append-only. The repository reads two flags to decide what to rewrite and calls
`mark_saved()` afterwards: `current_parse_changed` (a parse was applied or undone since load:
replace the items and the issues) and `items_changed` (only an item edit: replace the items,
leave the issues and their resolutions alone).
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

from src.domain.edits import ITEM_FIELDS, RECEIPT_FIELDS, Edit
from src.domain.enums import (
    EditTarget,
    IssueResolution,
    IssueSeverity,
    IssueSource,
    ReceiptStatus,
)
from src.domain.parse import Parse, ParsedIssue, ParsedItem, ParseOutcome
from src.exception import (
    DuplicatePhoto,
    InvalidEdit,
    InvalidIssueResolution,
    InvalidReceiptData,
    InvalidReceiptTransition,
    UnknownIssue,
    UnknownParse,
)

__all__ = [
    "Edit",
    "Header",
    "Issue",
    "Item",
    "Parse",
    "ParseOutcome",
    "ParsedIssue",
    "ParsedItem",
    "Photo",
    "Receipt",
]

MONEY_TOLERANCE = Decimal("0.02")
S = ReceiptStatus
# Statuses that may receive a new parse, an undo, an edit.
_PARSEABLE = {S.PENDING, S.PARSING, S.PARSED, S.FAILED, S.NOT_RECEIPT, S.AWAITING_MATCH}
_UNDOABLE = {S.PARSED, S.FAILED, S.NOT_RECEIPT, S.AWAITING_MATCH}


@dataclass(kw_only=True)
class Photo:
    telegram_file_unique_id: str | None = None
    telegram_file_id: str | None = None
    telegram_message_id: int | None = None
    path: str | None = None  # relative to RECEIPTS_DIR; None until the bytes are stored
    mime_type: str | None = None
    size_bytes: int | None = None
    received_at: datetime
    id: int | None = None

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            raise InvalidReceiptData("received_at must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class Header:
    """Receipt-level facts: the current parse with the edits applied."""

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
    """An item of the current parse with edits applied. `ref` is its `product_key#occurrence`."""

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


@dataclass(kw_only=True)
class Receipt:
    user_id: int
    id: int | None = None
    status: ReceiptStatus = S.PENDING
    header: Header = field(default_factory=Header)
    photos: list[Photo] = field(default_factory=list)
    parses: list[Parse] = field(default_factory=list)
    current_parse: Parse | None = None
    items: list[Item] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)  # the active ones
    edits: list[Edit] = field(default_factory=list)
    merged_into_id: int | None = None
    deleted_at: datetime | None = None
    error_message: str | None = None

    # Change tracking for the repository (see module docstring); reset by `mark_saved()`.
    current_parse_changed: bool = field(default=False, init=False, repr=False)
    items_changed: bool = field(default=False, init=False, repr=False)

    @classmethod
    def start(cls, user_id: int, photo: Photo) -> Receipt:
        return cls(user_id=user_id, photos=[photo])

    # --- photos and parses -------------------------------------------------------------

    def attach_photo(self, photo: Photo) -> None:
        self._ensure_open()
        unique_id = photo.telegram_file_unique_id
        if unique_id is not None and any(
            p.telegram_file_unique_id == unique_id for p in self.photos
        ):
            raise DuplicatePhoto(unique_id)
        self.photos.append(photo)

    def apply_parse(self, parse: Parse) -> ParseOutcome:
        """Make `parse` current and rebuild header, items and issues from it."""
        self._ensure_open()
        if self.status not in _PARSEABLE:
            raise InvalidReceiptTransition(f"cannot parse a {self.status} receipt")
        self.parses.append(parse)
        return self._switch_to(parse, refine=True)

    def undo_to(self, parse_id: int) -> ParseOutcome:
        """Make an earlier, stored parse current again. All edits are kept."""
        self._ensure_open()
        if self.status not in _UNDOABLE:
            raise InvalidReceiptTransition(f"cannot undo a {self.status} receipt")
        parse = next((p for p in self.parses if p.id == parse_id), None)
        if parse is None:
            raise UnknownParse(parse_id)
        # Undo does not answer the "same receipt?" question, so awaiting_match stays.
        return self._switch_to(parse, refine=False)

    def assign_parse_id(self, parse: Parse, parse_id: int) -> Parse:
        """For the repository: record the id a new parse was stored under."""
        stored = replace(parse, id=parse_id)
        self.parses = [stored if p is parse else p for p in self.parses]
        if self.current_parse is parse:
            self.current_parse = stored
        return stored

    # --- edits and issues --------------------------------------------------------------

    def record_edit(self, edit: Edit) -> None:
        """Keep the user's value on top of every parse, now and after any re-parse."""
        self._ensure_open()
        if self.current_parse is None or not self.current_parse.is_receipt:
            raise InvalidReceiptTransition("only a parsed receipt can be edited")
        if edit.target is EditTarget.ITEM and all(i.ref != edit.item_ref for i in self.items):
            raise InvalidEdit(f"the receipt has no item {edit.item_ref}")
        self.edits.append(edit)
        self.header, self.items = self._with_edits(self.current_parse)
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

    # --- status transitions ------------------------------------------------------------

    def merge_into(self, target_id: int) -> None:
        self._transition({S.PENDING, S.PARSED, S.AWAITING_MATCH}, S.MERGED)
        if self.id is not None and target_id == self.id:
            raise InvalidReceiptTransition("a receipt cannot be merged into itself")
        self.merged_into_id = target_id

    def mark_failed(self, reason: str) -> None:
        self._transition({S.PENDING, S.PARSING, S.FAILED}, S.FAILED)
        self.error_message = reason

    def mark_not_receipt(self) -> None:
        self._transition({S.PENDING, S.PARSING, S.FAILED}, S.NOT_RECEIPT)
        self.issues = []
        self._clear_items()

    def mark_awaiting_match(self) -> None:
        self._transition({S.PARSED}, S.AWAITING_MATCH)

    def soft_delete(self, at: datetime | None = None) -> None:
        if self.deleted_at is not None:
            raise InvalidReceiptTransition("the receipt is already deleted")
        self.deleted_at = at or datetime.now(UTC)

    # --- for the repository ------------------------------------------------------------

    def mark_saved(self) -> None:
        self.current_parse_changed = False
        self.items_changed = False

    # --- internals ---------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self.deleted_at is not None:
            raise InvalidReceiptTransition("the receipt is deleted")
        if self.status is S.MERGED:
            raise InvalidReceiptTransition(f"the receipt was merged into {self.merged_into_id}")

    def _transition(self, allowed: set[ReceiptStatus], new: ReceiptStatus) -> None:
        self._ensure_open()
        if self.status not in allowed:
            raise InvalidReceiptTransition(f"cannot go from {self.status} to {new}")
        self.status = new
        if new is not S.FAILED:
            self.error_message = None

    def _clear_items(self) -> None:
        self.items = []
        self.items_changed = True

    def _switch_to(self, parse: Parse, *, refine: bool) -> ParseOutcome:
        previous = _used_keys(self.current_parse)
        self.current_parse = parse
        self.header, self.items = self._with_edits(parse)
        self.issues = [Issue.of(i) for i in parse.issues]
        if parse.is_receipt:
            self.issues += self._conflicts(parse)
        if not parse.is_receipt:
            self.status = S.NOT_RECEIPT
        elif self.status is not S.AWAITING_MATCH or refine:
            self.status = S.PARSED
        self.error_message = None
        self.current_parse_changed = True
        used = _used_keys(parse)
        return ParseOutcome(product_keys_used=used, product_keys_released=previous - used)

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
