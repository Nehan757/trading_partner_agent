"""
Integration tests for pipeline/response_parser.py.
Verifies: LLM extraction feeds into deterministic re-validation, status transitions,
field safety (non-problem fields never overwritten), and error handling.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from models import PartnerState, PartnerStatus, FieldIssue
from pipeline.response_parser import parse_response


def _mock_completion(extracted: dict) -> MagicMock:
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps(extracted)
    return mock


def _make_partner(issues: list[FieldIssue], raw_response: str = "some reply", **kwargs) -> PartnerState:
    defaults = dict(name="Test LLC", email="test@test.com", trn=None, address=None, peppol_id=None)
    defaults.update(kwargs)
    p = PartnerState(**defaults)
    p.issues = issues
    p.status = PartnerStatus.OUTREACH_READY
    p.raw_response = raw_response
    return p


# ── Status transitions ────────────────────────────────────────────────────────

class TestStatusTransitions:
    def test_resolved_when_all_extracted_and_valid(self):
        partner = _make_partner([
            FieldIssue("trn", "missing"),
            FieldIssue("address", "missing"),
            FieldIssue("peppol_id", "missing"),
        ])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678901",
                "address": "Tower 1, Sheikh Zayed Road, Dubai, 12345",
                "peppol_id": "0088:1234567890123",
            })
            result = parse_response(partner)

        assert result.status == PartnerStatus.RESOLVED
        assert result.remaining_issues == []

    def test_partially_resolved_when_some_fields_still_missing(self):
        partner = _make_partner([
            FieldIssue("trn", "missing"),
            FieldIssue("peppol_id", "missing"),
        ])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678901",
                # peppol_id not in reply
            })
            result = parse_response(partner)

        assert result.status == PartnerStatus.PARTIALLY_RESOLVED
        assert len(result.remaining_issues) == 1
        assert result.remaining_issues[0].field == "peppol_id"

    def test_unresolved_when_extracted_value_fails_deterministic_validation(self):
        partner = _make_partner([FieldIssue("trn", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "INVALID_NOT_15_DIGITS",
            })
            result = parse_response(partner)

        assert result.status == PartnerStatus.UNRESOLVED
        assert len(result.remaining_issues) == 1
        assert result.remaining_issues[0].field == "trn"

    def test_unresolved_when_llm_returns_no_useful_fields(self):
        partner = _make_partner([FieldIssue("trn", "missing"), FieldIssue("peppol_id", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({})
            result = parse_response(partner)

        assert result.status == PartnerStatus.UNRESOLVED
        assert len(result.remaining_issues) == 2


# ── Field safety ──────────────────────────────────────────────────────────────

class TestFieldSafety:
    def test_does_not_overwrite_valid_non_problem_fields(self):
        # Email was valid in source data — LLM must not be allowed to change it.
        partner = _make_partner(
            [FieldIssue("trn", "missing")],
            email="original@test.com",
        )
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678901",
                "email": "replaced@evil.com",
            })
            result = parse_response(partner)

        assert result.email == "original@test.com"

    def test_only_problem_fields_are_updated(self):
        partner = _make_partner(
            [FieldIssue("peppol_id", "missing")],
            trn="100312345678901",   # already valid
        )
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "peppol_id": "0088:1234567890",
                "trn": "999999999999999",  # should be ignored
            })
            result = parse_response(partner)

        assert result.trn == "100312345678901"   # unchanged
        assert result.peppol_id == "0088:1234567890"


# ── LLM extraction specifics ──────────────────────────────────────────────────

class TestExtractionBehaviour:
    def test_extracted_data_stored_on_partner(self):
        partner = _make_partner([FieldIssue("trn", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345678901",
            })
            result = parse_response(partner)

        assert result.extracted_data == {"trn": "100312345678901"}

    def test_strips_dashes_from_trn_when_llm_cleans_correctly(self):
        # The LLM prompt instructs it to strip dashes before returning.
        # This test verifies that a correctly cleaned value passes validation.
        partner = _make_partner([FieldIssue("trn", "invalid: wrong length")])
        partner.trn = "1003-1234-5600039"

        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "trn": "100312345600039",  # dashes stripped by LLM
            })
            result = parse_response(partner)

        assert result.trn == "100312345600039"
        assert result.status == PartnerStatus.RESOLVED

    def test_ambiguous_peppol_reconstructed_as_scheme_colon_value(self):
        # Simulates: "our scheme is 0088 and value is 9876543210123"
        # LLM prompt asks it to reconstruct as scheme:value.
        partner = _make_partner([FieldIssue("peppol_id", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({
                "peppol_id": "0088:9876543210123",
            })
            result = parse_response(partner)

        assert result.peppol_id == "0088:9876543210123"
        assert result.status == PartnerStatus.RESOLVED

    def test_uses_json_response_format(self):
        partner = _make_partner([FieldIssue("trn", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({"trn": "100312345678901"})
            parse_response(partner)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}

    def test_temperature_is_zero(self):
        partner = _make_partner([FieldIssue("trn", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion({"trn": "100312345678901"})
            parse_response(partner)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("temperature") == 0


# ── Error handling ────────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_invalid_json_from_llm_leaves_partner_unresolved(self):
        # response_format=json_object makes this unlikely in production, but
        # the fallback must still handle it gracefully without raising.
        partner = _make_partner([FieldIssue("trn", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            bad = MagicMock()
            bad.choices[0].message.content = "not valid json {"
            mock_client.chat.completions.create.return_value = bad
            result = parse_response(partner)

        assert result.extracted_data == {}
        assert result.status == PartnerStatus.UNRESOLVED

    def test_openai_api_error_propagates(self):
        # API failures (auth, rate limit, network) should raise, not be swallowed.
        from openai import OpenAIError
        partner = _make_partner([FieldIssue("trn", "missing")])
        with patch("pipeline.response_parser.client") as mock_client:
            mock_client.chat.completions.create.side_effect = OpenAIError("api error")
            with pytest.raises(OpenAIError):
                parse_response(partner)

    def test_skips_partner_with_no_raw_response(self):
        partner = _make_partner([FieldIssue("trn", "missing")], raw_response=None)
        with patch("pipeline.response_parser.client") as mock_client:
            result = parse_response(partner)

        mock_client.chat.completions.create.assert_not_called()
        assert result.status == PartnerStatus.OUTREACH_READY  # unchanged
