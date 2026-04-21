import re
from models import FieldIssue, PartnerState, PartnerStatus

# All validation here is intentionally deterministic — these are structural rules
# with exact, enumerable criteria. Using an LLM for any of these checks would
# add latency, cost, and non-determinism with no accuracy benefit.

TRN_RE = re.compile(r"^\d{15}$")
PEPPOL_RE = re.compile(r"^[^:\s]+:[^:\s]+$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _check_email(value: str | None) -> FieldIssue | None:
    if not value:
        return FieldIssue("email", "missing")
    if not EMAIL_RE.match(value):
        return FieldIssue("email", f"invalid format: '{value}'")
    return None


def _check_trn(value: str | None) -> FieldIssue | None:
    if not value:
        return FieldIssue("trn", "missing")
    if not TRN_RE.match(value):
        return FieldIssue("trn", f"must be exactly 15 digits, got '{value}' ({len(value)} chars)")
    return None


def _check_address(value: str | None) -> FieldIssue | None:
    if not value:
        return FieldIssue("address", "missing")
    # A structured e-invoicing address must contain comma-separated components
    # (e.g. "Building, Street, City, Postal Code"). Bare city names like "Dubai"
    # or informal strings like "Dubai near the mall" are rejected.
    if "," not in value:
        return FieldIssue("address", f"unstructured — must include comma-separated components (street, city, postal code): got '{value}'")
    return None


def _check_peppol_id(value: str | None) -> FieldIssue | None:
    if not value:
        return FieldIssue("peppol_id", "missing")
    if not PEPPOL_RE.match(value):
        return FieldIssue("peppol_id", f"must be scheme:value format (e.g. 0088:1234567890123), got '{value}'")
    return None


_VALIDATORS = {
    "email": _check_email,
    "trn": _check_trn,
    "address": _check_address,
    "peppol_id": _check_peppol_id,
}


def validate_field(field_name: str, value: str | None) -> FieldIssue | None:
    fn = _VALIDATORS.get(field_name)
    return fn(value) if fn else None


def validate_partner(partner: PartnerState) -> PartnerState:
    issues = []
    for field_name, fn in _VALIDATORS.items():
        issue = fn(getattr(partner, field_name))
        if issue:
            issues.append(issue)

    partner.issues = issues

    if not issues:
        partner.status = PartnerStatus.RESOLVED
    elif any(i.field == "email" for i in issues):
        # Cannot send outreach without a valid email — mark separately so
        # the report can surface it as a manual intervention case.
        partner.status = PartnerStatus.NO_EMAIL
    else:
        partner.status = PartnerStatus.OUTREACH_READY

    return partner
