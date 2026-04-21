import json
from openai import OpenAI
from models import PartnerState, PartnerStatus
from pipeline.validator import validate_field

# Lazily initialized so load_dotenv() in main.py can run before the first API call.
client: OpenAI | None = None


def _get_client() -> OpenAI:
    global client
    if client is None:
        client = OpenAI()
    return client


_EXTRACT_PROMPT = """You are a data extraction assistant for an e-invoicing platform.

Extract trading partner information from the email reply below. Return a JSON object containing only the fields you can confidently identify. Use these exact keys:
- "trn": Tax Registration Number — digits only, strip any spaces, dashes, or punctuation
- "peppol_id": Peppol ID — reconstruct as scheme:value (e.g. if the reply says "scheme 0088, value 9876543", return "0088:9876543")
- "address": Full address exactly as written
- "email": Email address

Rules:
- Omit any field that is not mentioned or is genuinely ambiguous
- Do not guess or hallucinate values
- For TRN: strip all non-digit characters before returning
- For peppol_id: always use colon-separated scheme:value format

Email reply:
{response_text}

Return only valid JSON, no explanation."""


def parse_response(partner: PartnerState) -> PartnerState:
    if not partner.raw_response:
        return partner

    result = _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(
            response_text=partner.raw_response
        )}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        extracted = json.loads(result.choices[0].message.content)
    except json.JSONDecodeError:
        extracted = {}

    partner.extracted_data = extracted

    # Only update fields that were originally problematic — never overwrite
    # fields that were already valid in the source data.
    for field_name in partner.problem_fields:
        if field_name in extracted:
            setattr(partner, field_name, extracted[field_name])

    # Re-run deterministic validation on updated fields.
    # The LLM extraction is the first pass; deterministic rules are the final gate.
    partner.remaining_issues = [
        issue
        for field_name in partner.problem_fields
        if (issue := validate_field(field_name, getattr(partner, field_name))) is not None
    ]

    resolved_count = len(partner.issues) - len(partner.remaining_issues)

    if not partner.remaining_issues:
        partner.status = PartnerStatus.RESOLVED
    elif resolved_count > 0:
        partner.status = PartnerStatus.PARTIALLY_RESOLVED
    else:
        partner.status = PartnerStatus.UNRESOLVED

    return partner
