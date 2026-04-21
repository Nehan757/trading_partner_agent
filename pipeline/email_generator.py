from openai import OpenAI
from models import PartnerState, PartnerStatus

# Lazily initialized so load_dotenv() in main.py can run before the first API call.
client: OpenAI | None = None


def _get_client() -> OpenAI:
    global client
    if client is None:
        client = OpenAI()
    return client

_SYSTEM_PROMPT = (
    "You are a professional accounts payable coordinator at an e-invoicing platform. "
    "Write clear, polite, concise emails. Never include a subject line. "
    "Keep responses under 150 words."
)

_USER_TEMPLATE = """Write an outreach email to {partner_name} requesting the following missing or invalid trading partner information:

{issues_list}

Field requirements for context:
- trn: Tax Registration Number — must be exactly 15 digits
- peppol_id: Peppol network ID in scheme:value format (e.g. 0088:1234567890123)
- address: Full structured billing address with street, city, and postal code separated by commas
- email: Valid invoicing contact email address

Be specific about format requirements. If a field is invalid (not just missing), briefly explain why it was rejected. Start with "Dear {partner_name} team,"."""


def generate_outreach_email(partner: PartnerState) -> PartnerState:
    if partner.status != PartnerStatus.OUTREACH_READY:
        return partner

    issues_list = "\n".join(f"- {issue}" for issue in partner.issues)

    response = _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_TEMPLATE.format(
                partner_name=partner.name,
                issues_list=issues_list,
            )},
        ],
        temperature=0.3,
    )

    partner.outreach_email = response.choices[0].message.content.strip()
    return partner
