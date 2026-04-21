from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PartnerStatus(str, Enum):
    PENDING = "pending"
    NO_EMAIL = "no_email"                   # Cannot contact — email missing/invalid
    OUTREACH_READY = "outreach_ready"       # Email generated, awaiting response
    NO_RESPONSE = "no_response"             # Outreach sent, no reply received
    RESOLVED = "resolved"                   # All fields valid
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"               # Response received but still invalid/missing


@dataclass
class FieldIssue:
    field: str
    issue: str  # "missing" or "invalid: <reason>"

    def __str__(self) -> str:
        return f"{self.field}: {self.issue}"


@dataclass
class PartnerState:
    name: str
    email: Optional[str]
    trn: Optional[str]
    address: Optional[str]
    peppol_id: Optional[str]

    # Populated after Stage 2 (validation)
    issues: list[FieldIssue] = field(default_factory=list)

    # Populated after Stage 3 (outreach generation)
    outreach_email: Optional[str] = None

    # Populated after Stage 4 (response loading)
    raw_response: Optional[str] = None

    # Populated after Stage 5 (response parsing)
    extracted_data: dict = field(default_factory=dict)
    remaining_issues: list[FieldIssue] = field(default_factory=list)

    status: PartnerStatus = PartnerStatus.PENDING

    @property
    def problem_fields(self) -> set[str]:
        return {issue.field for issue in self.issues}
