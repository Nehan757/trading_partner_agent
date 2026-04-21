"""
Integration tests for pipeline/email_generator.py.
OpenAI client is mocked — tests verify prompt construction and pipeline behaviour,
not LLM output quality.
"""
from unittest.mock import MagicMock, patch
from models import PartnerState, PartnerStatus, FieldIssue
from pipeline.email_generator import generate_outreach_email


def _mock_completion(body: str) -> MagicMock:
    mock = MagicMock()
    mock.choices[0].message.content = body
    return mock


def _outreach_partner(**overrides) -> PartnerState:
    p = PartnerState(
        name="Test LLC",
        email="test@test.com",
        trn=None,
        address=None,
        peppol_id=None,
    )
    p.issues = [
        FieldIssue("trn", "missing"),
        FieldIssue("address", "missing"),
        FieldIssue("peppol_id", "missing"),
    ]
    p.status = PartnerStatus.OUTREACH_READY
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


class TestGenerateOutreachEmail:
    def test_generates_email_for_outreach_ready(self):
        partner = _outreach_partner()
        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion(
                "Dear Test LLC team,\n\nPlease provide your missing details."
            )
            result = generate_outreach_email(partner)

        assert result.outreach_email is not None
        assert len(result.outreach_email) > 0
        mock_client.chat.completions.create.assert_called_once()

    def test_skips_no_email_partner(self):
        partner = _outreach_partner(status=PartnerStatus.NO_EMAIL)
        with patch("pipeline.email_generator.client") as mock_client:
            result = generate_outreach_email(partner)

        mock_client.chat.completions.create.assert_not_called()
        assert result.outreach_email is None

    def test_skips_resolved_partner(self):
        partner = _outreach_partner(status=PartnerStatus.RESOLVED)
        with patch("pipeline.email_generator.client") as mock_client:
            generate_outreach_email(partner)

        mock_client.chat.completions.create.assert_not_called()

    def test_prompt_includes_partner_name(self):
        partner = _outreach_partner(name="Emirates NBD")
        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion("email body")
            generate_outreach_email(partner)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        full_prompt = " ".join(m["content"] for m in messages)
        assert "Emirates NBD" in full_prompt

    def test_prompt_includes_all_issue_fields(self):
        partner = _outreach_partner()
        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion("email body")
            generate_outreach_email(partner)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        assert "trn" in user_message
        assert "address" in user_message
        assert "peppol_id" in user_message

    def test_uses_gpt4o_mini(self):
        partner = _outreach_partner()
        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion("email body")
            generate_outreach_email(partner)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"

    def test_single_missing_field_only_mentions_that_field(self):
        partner = _outreach_partner()
        partner.issues = [FieldIssue("peppol_id", "missing")]

        with patch("pipeline.email_generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = _mock_completion("email body")
            generate_outreach_email(partner)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        assert "peppol_id" in user_message
        # trn and address should not appear as issues in the prompt
        assert "trn: missing" not in user_message
        assert "address: missing" not in user_message
