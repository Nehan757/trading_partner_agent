"""
End-to-end integration tests for the full pipeline.
All LLM calls are mocked — tests verify stage sequencing, state handoff between
stages, and correct final status distribution across a realistic partner set.
"""
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from models import PartnerStatus
from pipeline.loader import load_csv
from pipeline.validator import validate_partner
from pipeline.email_generator import generate_outreach_email
from pipeline.response_parser import parse_response


def _mock_completion(content) -> MagicMock:
    mock = MagicMock()
    mock.choices[0].message.content = content if isinstance(content, str) else json.dumps(content)
    return mock


def write_temp_csv(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


@pytest.fixture
def three_partner_csv(tmp_path):
    content = (
        "partner_name,email,trn,address,peppol_id\n"
        # Has email, missing trn + peppol_id, unstructured address
        "Alpha Corp,alpha@test.com,,Dubai near the mall,\n"
        # No email — cannot contact
        "Beta LLC,,100312345678901,\"Road, Town, 12345\",0088:1234567\n"
        # All fields valid — should be immediately resolved
        "Gamma Inc,gamma@test.com,100312345678902,\"Ave, Metro, 11111\",0088:9999999\n"
    )
    p = tmp_path / "partners.csv"
    p.write_text(content)
    return str(p)


# ── Stage 2: Validation ───────────────────────────────────────────────────────

class TestValidationStage:
    def test_correct_status_assigned_per_partner(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        statuses = {p.name: p.status for p in partners}

        assert statuses["Alpha Corp"] == PartnerStatus.OUTREACH_READY
        assert statuses["Beta LLC"] == PartnerStatus.NO_EMAIL
        assert statuses["Gamma Inc"] == PartnerStatus.RESOLVED

    def test_resolved_partner_has_no_issues(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        gamma = next(p for p in partners if p.name == "Gamma Inc")
        assert gamma.issues == []

    def test_no_email_partner_has_email_in_issues(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        beta = next(p for p in partners if p.name == "Beta LLC")
        assert any(i.field == "email" for i in beta.issues)


# ── Stage 3: Outreach generation ─────────────────────────────────────────────

class TestOutreachStage:
    def test_resolved_partner_skips_outreach(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        gamma = next(p for p in partners if p.name == "Gamma Inc")

        with patch("pipeline.email_generator.client") as mock_client:
            generate_outreach_email(gamma)

        mock_client.chat.completions.create.assert_not_called()

    def test_no_email_partner_skips_outreach(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        beta = next(p for p in partners if p.name == "Beta LLC")

        with patch("pipeline.email_generator.client") as mock_client:
            generate_outreach_email(beta)

        mock_client.chat.completions.create.assert_not_called()

    def test_outreach_ready_partner_gets_email(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        alpha = next(p for p in partners if p.name == "Alpha Corp")

        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion("Dear Alpha Corp team,")
            result = generate_outreach_email(alpha)

        assert result.outreach_email == "Dear Alpha Corp team,"
        mock_client.chat.completions.create.assert_called_once()


# ── Stage 5: Response parsing → re-validation ─────────────────────────────────

class TestParseAndRevalidateStage:
    def test_complete_response_resolves_partner(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        alpha = next(p for p in partners if p.name == "Alpha Corp")
        alpha.raw_response = "Our TRN is 100312345678999, Peppol 0088:7654321, address: Tower 1, Zayed Road, Dubai, 12345"

        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678999",
                "peppol_id": "0088:7654321",
                "address": "Tower 1, Zayed Road, Dubai, 12345",
            })
            result = parse_response(alpha)

        assert result.status == PartnerStatus.RESOLVED

    def test_partial_response_partially_resolves_partner(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        alpha = next(p for p in partners if p.name == "Alpha Corp")
        alpha.raw_response = "Our TRN is 100312345678999 but we don't have a Peppol ID yet."

        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678999",
                # peppol_id and address not provided
            })
            result = parse_response(alpha)

        assert result.status == PartnerStatus.PARTIALLY_RESOLVED
        remaining_fields = {i.field for i in result.remaining_issues}
        assert "trn" not in remaining_fields
        assert "peppol_id" in remaining_fields


# ── Full pipeline flow ────────────────────────────────────────────────────────

class TestFullPipelineFlow:
    def test_state_accumulates_correctly_across_stages(self, three_partner_csv):
        # Stage 1 + 2
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        alpha = next(p for p in partners if p.name == "Alpha Corp")
        assert alpha.status == PartnerStatus.OUTREACH_READY
        assert alpha.outreach_email is None

        # Stage 3
        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion("email body")
            alpha = generate_outreach_email(alpha)
        assert alpha.outreach_email == "email body"

        # Stage 4 (simulate response loading)
        alpha.raw_response = "TRN: 100312345678901, Peppol: 0088:1111111, Address: Block A, Main St, Dubai, 00001"

        # Stage 5
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678901",
                "peppol_id": "0088:1111111",
                "address": "Block A, Main St, Dubai, 00001",
            })
            alpha = parse_response(alpha)

        assert alpha.status == PartnerStatus.RESOLVED
        assert alpha.trn == "100312345678901"
        assert alpha.peppol_id == "0088:1111111"
        assert alpha.extracted_data != {}

    def test_no_response_partner_keeps_outreach_ready_status(self, three_partner_csv):
        partners = [validate_partner(p) for p in load_csv(three_partner_csv)]
        alpha = next(p for p in partners if p.name == "Alpha Corp")

        # Simulate no response received → mark as NO_RESPONSE in main.py
        alpha.status = PartnerStatus.NO_RESPONSE

        # parse_response should not run (raw_response is None)
        with patch("pipeline.response_parser.client") as mock_client:
            result = parse_response(alpha)

        mock_client.chat.completions.create.assert_not_called()
        assert result.status == PartnerStatus.NO_RESPONSE
