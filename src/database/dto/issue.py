from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.domain.enums import IssueResolution


class NewReceiptIssueDTO(BaseModel):
    parse_id: int
    # Plain strings: the database CHECK is the single source of truth for valid values.
    source: str
    issue_type: str
    severity: str
    message: str
    field: str | None = None
    item_name_raw: str | None = None
    resolution: str = IssueResolution.OPEN.value


class ReceiptIssueDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    parse_id: int
    source: str
    issue_type: str
    severity: str
    message: str
    field: str | None
    item_name_raw: str | None
    resolution: str
    resolved_at: datetime | None
    created_at: datetime
