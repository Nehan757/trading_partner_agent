"""
Unit tests for pipeline/loader.py — CSV parsing and column normalisation.
No I/O beyond temp files, no LLM calls.
"""
import os
import tempfile
from pipeline.loader import load_csv, _normalize_header, _clean


# ── Header normalisation ──────────────────────────────────────────────────────

class TestNormalizeHeader:
    def test_canonical_names_pass_through(self):
        for name in ("partner_name", "email", "trn", "address", "peppol_id"):
            assert _normalize_header(name) == name

    def test_strips_whitespace_and_lowercases(self):
        assert _normalize_header("  Partner_Name  ") == "partner_name"
        assert _normalize_header("EMAIL") == "email"
        assert _normalize_header("TRN") == "trn"

    def test_spaces_treated_as_underscores(self):
        assert _normalize_header("partner name") == "partner_name"
        assert _normalize_header("peppol id") == "peppol_id"

    def test_aliases_map_to_canonical(self):
        assert _normalize_header("vendor_name") == "partner_name"
        assert _normalize_header("supplier_name") == "partner_name"
        assert _normalize_header("tax_registration_number") == "trn"
        assert _normalize_header("vat_number") == "trn"
        assert _normalize_header("peppol") == "peppol_id"
        assert _normalize_header("peppol_identifier") == "peppol_id"
        assert _normalize_header("billing_address") == "address"

    def test_unknown_header_passes_through_unchanged(self):
        assert _normalize_header("some_unknown_col") == "some_unknown_col"

    def test_hyphen_treated_as_underscore(self):
        assert _normalize_header("e-mail") == "email"


# ── Value cleaning ────────────────────────────────────────────────────────────

class TestClean:
    def test_strips_surrounding_whitespace(self):
        assert _clean("  hello  ") == "hello"

    def test_empty_string_returns_none(self):
        assert _clean("") is None

    def test_whitespace_only_returns_none(self):
        assert _clean("   ") is None

    def test_none_returns_none(self):
        assert _clean(None) is None

    def test_valid_value_unchanged(self):
        assert _clean("procurement@test.ae") == "procurement@test.ae"
        assert _clean("100312345678901") == "100312345678901"


# ── CSV loading ───────────────────────────────────────────────────────────────

def write_temp_csv(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


class TestLoadCsv:
    def test_loads_standard_schema(self):
        path = write_temp_csv(
            "partner_name,email,trn,address,peppol_id\n"
            'Test LLC,test@test.com,100312345678901,"Building, Street, City",0088:123\n'
        )
        partners = load_csv(path)
        os.unlink(path)

        assert len(partners) == 1
        p = partners[0]
        assert p.name == "Test LLC"
        assert p.email == "test@test.com"
        assert p.trn == "100312345678901"
        assert p.peppol_id == "0088:123"

    def test_empty_fields_become_none(self):
        path = write_temp_csv(
            "partner_name,email,trn,address,peppol_id\n"
            "Test LLC,,,,\n"
        )
        partners = load_csv(path)
        os.unlink(path)

        p = partners[0]
        assert p.email is None
        assert p.trn is None
        assert p.address is None
        assert p.peppol_id is None

    def test_whitespace_only_fields_become_none(self):
        path = write_temp_csv(
            "partner_name,email,trn,address,peppol_id\n"
            "Test LLC,   ,  ,  ,  \n"
        )
        partners = load_csv(path)
        os.unlink(path)

        assert partners[0].email is None
        assert partners[0].trn is None

    def test_loads_multiple_rows_in_order(self):
        path = write_temp_csv(
            "partner_name,email,trn,address,peppol_id\n"
            "Alpha,,,,\n"
            "Beta,,,,\n"
            "Gamma,,,,\n"
        )
        partners = load_csv(path)
        os.unlink(path)

        assert len(partners) == 3
        assert [p.name for p in partners] == ["Alpha", "Beta", "Gamma"]

    def test_aliased_column_names_are_normalised(self):
        path = write_temp_csv(
            "vendor_name,email,tax_registration_number,billing_address,peppol\n"
            'Test LLC,test@test.com,100312345678901,"Building, Street, City",0088:123\n'
        )
        partners = load_csv(path)
        os.unlink(path)

        p = partners[0]
        assert p.name == "Test LLC"
        assert p.trn == "100312345678901"
        assert p.peppol_id == "0088:123"
        assert "Building" in p.address

    def test_quoted_address_with_commas_parsed_correctly(self):
        path = write_temp_csv(
            "partner_name,email,trn,address,peppol_id\n"
            'Test LLC,t@t.com,,\"Floor 4, Sheikh Zayed Road, Dubai\",\n'
        )
        partners = load_csv(path)
        os.unlink(path)

        assert partners[0].address == "Floor 4, Sheikh Zayed Road, Dubai"
