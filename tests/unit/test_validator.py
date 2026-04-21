"""
Unit tests for pipeline/validator.py — all deterministic, no I/O, no LLM calls.
"""
from models import PartnerState, PartnerStatus
from pipeline.validator import (
    validate_partner,
    validate_field,
    _check_email,
    _check_trn,
    _check_address,
    _check_peppol_id,
)


# ── TRN ──────────────────────────────────────────────────────────────────────

class TestTrn:
    def test_valid(self):
        assert _check_trn("100312345678901") is None

    def test_missing(self):
        issue = _check_trn(None)
        assert issue.field == "trn"
        assert issue.issue == "missing"

    def test_too_short(self):
        issue = _check_trn("12345678901")
        assert issue is not None
        assert "15 digits" in issue.issue

    def test_too_long(self):
        assert _check_trn("10031234560000399") is not None   # 17 chars

    def test_contains_letters(self):
        assert _check_trn("TRN12345678901") is not None

    def test_dashes_rejected(self):
        # Dashes are the LLM parser's responsibility to strip before we validate.
        assert _check_trn("1003-1234-56001") is not None

    def test_spaces_rejected(self):
        assert _check_trn("100312 345678901") is not None

    def test_exactly_15_zeros_is_valid(self):
        # Format-only check — business rules around all-zeros are out of scope.
        assert _check_trn("000000000000000") is None


# ── Peppol ID ─────────────────────────────────────────────────────────────────

class TestPeppolId:
    def test_valid(self):
        assert _check_peppol_id("0088:1234567890123") is None

    def test_missing(self):
        issue = _check_peppol_id(None)
        assert issue.field == "peppol_id"
        assert issue.issue == "missing"

    def test_no_colon(self):
        assert _check_peppol_id("00881234567890123") is not None

    def test_empty_scheme(self):
        assert _check_peppol_id(":1234567890123") is not None

    def test_empty_value(self):
        assert _check_peppol_id("0088:") is not None

    def test_space_instead_of_colon(self):
        assert _check_peppol_id("0088 1234567890123") is not None

    def test_colon_in_value_is_rejected(self):
        # Peppol IDs are strictly scheme:value; colons are not valid in the value part.
        assert _check_peppol_id("0088:123:456") is not None


# ── Address ───────────────────────────────────────────────────────────────────

class TestAddress:
    def test_valid_structured(self):
        assert _check_address("Al Futtaim Tower, Sheikh Zayed Road, Dubai 12345") is None

    def test_missing(self):
        issue = _check_address(None)
        assert issue.field == "address"
        assert issue.issue == "missing"

    def test_bare_city_name(self):
        issue = _check_address("Dubai")
        assert issue is not None
        assert "comma" in issue.issue

    def test_informal_no_comma(self):
        issue = _check_address("Dubai near the mall")
        assert issue is not None
        assert "comma" in issue.issue

    def test_single_comma_is_sufficient(self):
        assert _check_address("Sheikh Zayed Road, Dubai") is None

    def test_multiple_commas(self):
        assert _check_address("Tower 1, Floor 4, Sheikh Zayed Road, Dubai, 12345") is None


# ── Email ─────────────────────────────────────────────────────────────────────

class TestEmail:
    def test_valid(self):
        assert _check_email("procurement@alfuttaim.ae") is None

    def test_missing(self):
        issue = _check_email(None)
        assert issue.field == "email"
        assert issue.issue == "missing"

    def test_no_at_sign(self):
        assert _check_email("notanemail.com") is not None

    def test_no_domain(self):
        assert _check_email("user@") is not None

    def test_no_tld(self):
        assert _check_email("user@domain") is not None

    def test_spaces_rejected(self):
        assert _check_email("user @domain.com") is not None


# ── validate_field dispatch ───────────────────────────────────────────────────

class TestValidateField:
    def test_dispatches_to_correct_validator(self):
        assert validate_field("trn", "100312345678901") is None
        assert validate_field("trn", None).field == "trn"
        assert validate_field("peppol_id", "0088:123") is None
        assert validate_field("email", None).field == "email"

    def test_unknown_field_returns_none(self):
        assert validate_field("unknown_field", "anything") is None


# ── validate_partner ──────────────────────────────────────────────────────────

class TestValidatePartner:
    def _make(self, **kwargs):
        defaults = dict(
            name="Test LLC",
            email="test@test.com",
            trn="100312345678901",
            address="Building 1, Sheikh Zayed Road, Dubai, 12345",
            peppol_id="0088:1234567890123",
        )
        defaults.update(kwargs)
        return PartnerState(**defaults)

    def test_all_valid_resolves(self):
        result = validate_partner(self._make())
        assert result.status == PartnerStatus.RESOLVED
        assert result.issues == []

    def test_missing_email_is_no_email(self):
        result = validate_partner(self._make(email=None))
        assert result.status == PartnerStatus.NO_EMAIL

    def test_invalid_email_is_no_email(self):
        result = validate_partner(self._make(email="not-an-email"))
        assert result.status == PartnerStatus.NO_EMAIL

    def test_missing_non_email_fields_is_outreach_ready(self):
        result = validate_partner(self._make(trn=None, peppol_id=None))
        assert result.status == PartnerStatus.OUTREACH_READY
        assert len(result.issues) == 2

    def test_invalid_trn_is_outreach_ready(self):
        result = validate_partner(self._make(trn="10031234560000399"))
        assert result.status == PartnerStatus.OUTREACH_READY
        assert any(i.field == "trn" for i in result.issues)

    def test_problem_fields_property(self):
        result = validate_partner(self._make(trn=None, address=None))
        assert result.problem_fields == {"trn", "address"}

    def test_issues_populated_correctly(self):
        result = validate_partner(self._make(trn=None, peppol_id="bad_no_colon"))
        fields = {i.field for i in result.issues}
        assert "trn" in fields
        assert "peppol_id" in fields
