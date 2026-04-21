from pathlib import Path
from dotenv import load_dotenv
from models import PartnerStatus
from pipeline.loader import load_csv, load_responses
from pipeline.validator import validate_partner
from pipeline.email_generator import generate_outreach_email
from pipeline.response_parser import parse_response
from pipeline.report import print_report

load_dotenv()  # must run before the first LLM call; lazy client init in pipeline modules ensures this is fine

_ROOT = Path(__file__).parent
PARTNERS_CSV = str(_ROOT / "data" / "partners.csv")
RESPONSES_JSON = str(_ROOT / "data" / "responses.json")


def _divider(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print('─'*60)


def run_pipeline() -> None:
    # ── Stage 1: Load ────────────────────────────────────────────
    _divider("Stage 1 — Loading partner data")
    partners = load_csv(PARTNERS_CSV)
    print(f"  Loaded {len(partners)} partners.")

    # ── Stage 2: Validate ─────────────────────────────────────────
    _divider("Stage 2 — Validating fields (deterministic)")
    partners = [validate_partner(p) for p in partners]
    for p in partners:
        if p.issues:
            print(f"  {p.name}: {len(p.issues)} issue(s) — {', '.join(i.field for i in p.issues)}")
        else:
            print(f"  {p.name}: all fields valid")

    # ── Stage 3: Generate outreach emails (LLM) ───────────────────
    _divider("Stage 3 — Generating outreach emails (LLM)")
    partners = [generate_outreach_email(p) for p in partners]

    for p in partners:
        if p.outreach_email:
            print(f"\n  ┌─ Email to {p.name} " + "─" * max(0, 40 - len(p.name)))
            for line in p.outreach_email.splitlines():
                print(f"  │ {line}")
            print("  └" + "─" * 50)
        elif p.status == PartnerStatus.NO_EMAIL:
            print(f"\n  ⚠ {p.name}: skipped — no valid email address")
        elif p.status == PartnerStatus.RESOLVED:
            print(f"\n  ✓ {p.name}: no outreach needed — already complete")

    # ── Stage 4: Load simulated responses ─────────────────────────
    _divider("Stage 4 — Loading simulated partner responses")
    responses = load_responses(RESPONSES_JSON)

    for p in partners:
        if p.name in responses:
            p.raw_response = responses[p.name]
            print(f"  {p.name}: response received")
        elif p.status == PartnerStatus.OUTREACH_READY:
            p.status = PartnerStatus.NO_RESPONSE
            print(f"  {p.name}: no response")

    # ── Stage 5: Parse responses (LLM) + re-validate (deterministic)
    _divider("Stage 5 — Parsing responses (LLM) + re-validating (deterministic)")
    partners = [parse_response(p) if p.raw_response else p for p in partners]

    for p in partners:
        if p.extracted_data:
            print(f"  {p.name}: extracted {list(p.extracted_data.keys())} → status: {p.status.value}")

    # ── Stage 6: Final report ─────────────────────────────────────
    print_report(partners)


if __name__ == "__main__":
    run_pipeline()
