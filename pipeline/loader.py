import csv
import json
from models import PartnerState

# Maps canonical field names to known column header variants.
#
# DESIGN NOTE — LLM-based column normalization:
# This alias dict handles common variations deterministically and works well
# when the schema is known or close to known. For a production system ingesting
# CSVs from many different ERP/accounting systems, the input space becomes
# unbounded: "Vndor Nme", "Tax Reg. No.", "PEPPOL Network ID", etc. In that
# case, a single cheap LLM call (gpt-4o-mini) to map arbitrary headers onto the
# canonical schema is justified — the cost of a wrong silent mapping far exceeds
# the cost of one LLM call per CSV ingestion.
COLUMN_ALIASES: dict[str, set[str]] = {
    "partner_name": {"name", "vendor_name", "supplier_name", "company_name", "partner"},
    "email": {"email_address", "contact_email", "e_mail", "mail"},
    "trn": {"tax_registration_number", "tax_reg_no", "tax_number", "trn_number", "vat_number"},
    "address": {"addr", "location", "billing_address", "full_address"},
    "peppol_id": {"peppol", "peppol_identifier", "peppolid", "peppol_network_id"},
}


def _normalize_header(header: str) -> str:
    normalized = header.strip().lower().replace(" ", "_").replace("-", "_")
    for canonical, aliases in COLUMN_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return normalized


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def load_csv(path: str) -> list[PartnerState]:
    partners = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        field_map = {_normalize_header(h): h for h in (reader.fieldnames or [])}

        for row in reader:
            r = {canonical: _clean(row.get(original)) for canonical, original in field_map.items()}
            partners.append(PartnerState(
                name=r.get("partner_name") or "",
                email=r.get("email"),
                trn=r.get("trn"),
                address=r.get("address"),
                peppol_id=r.get("peppol_id"),
            ))
    return partners


def load_responses(path: str) -> dict[str, str]:
    """Returns a mapping of partner_name → free-text reply. Partners absent from the dict have not responded."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
