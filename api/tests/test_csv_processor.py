"""Tests for csv_processor module."""

import io
import pandas as pd
import pytest

from csv_processor import (
    _excel_col_letter,
    parse_csv,
    parse_excel,
    parse_file,
    dataframe_to_csv_bytes,
    extract_lead_data,
    extract_all_leads,
    assemble_enriched_csv,
    OUTPUT_START_COL_INDEX,
)

from prompt_templates import _flatten_emails, _output_headers


# ---------------------------------------------------------------------------
# Helpers — build test CSVs
# ---------------------------------------------------------------------------

def _build_csv_bytes(rows: list[list[str]], num_cols: int = 75) -> bytes:
    """Build a CSV with the given rows, padding each row to num_cols columns.

    Column headers are Excel-style letters: A, B, C, ..., BV, BW, ...
    """
    def col_letter(idx: int) -> str:
        r = ""
        while True:
            r = chr(idx % 26 + ord("A")) + r
            idx = idx // 26 - 1
            if idx < 0:
                break
        return r

    headers = [col_letter(i) for i in range(num_cols)]
    buf = io.StringIO()
    buf.write(",".join(headers) + "\n")
    for row in rows:
        padded = row + [""] * (num_cols - len(row))
        buf.write(",".join(padded[:num_cols]) + "\n")
    return buf.getvalue().encode("utf-8")


def _make_lead_row() -> list[str]:
    """Return a single row with key columns filled in (A, B, K, L, W) and some demographics."""
    row = [""] * 75
    row[0] = "Microsoft 365 E5"                  # A  — license
    row[1] = "Streamline renewal process"         # B  — engagement objectives
    row[3] = "Technology"                         # D  — demographic
    row[4] = "500-1000"                           # E  — headcount
    row[10] = "Jane"                              # K  — first name
    row[11] = "Doe"                               # L  — last name
    row[22] = "Contoso Ltd"                       # W  — organization
    row[30] = "CFO"                               # AE — some extra demographic
    return row


# ---------------------------------------------------------------------------
# _excel_col_letter
# ---------------------------------------------------------------------------

class TestExcelColLetter:
    def test_single_letters(self):
        assert _excel_col_letter(0) == "A"
        assert _excel_col_letter(25) == "Z"

    def test_double_letters(self):
        assert _excel_col_letter(26) == "AA"
        assert _excel_col_letter(27) == "AB"
        assert _excel_col_letter(51) == "AZ"
        assert _excel_col_letter(52) == "BA"

    def test_column_bw(self):
        # BW should be index 74 (B=1 → 26+1=27 offset, W=22 → 26*2+22=74)
        assert _excel_col_letter(74) == "BW"


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------

class TestParseCSV:
    def test_basic_parse(self):
        csv_bytes = b"A,B,C\n1,2,3\n4,5,6\n"
        df = parse_csv(csv_bytes)
        assert len(df) == 2
        assert list(df.columns) == ["A", "B", "C"]
        assert df.iloc[0, 0] == "1"

    def test_preserves_strings(self):
        csv_bytes = b"A,B\n001,true\n"
        df = parse_csv(csv_bytes)
        # dtype=str should keep leading zeros and booleans as strings
        assert df.iloc[0, 0] == "001"
        assert df.iloc[0, 1] == "true"

    def test_empty_values_not_nan(self):
        csv_bytes = b"A,B\n,\n"
        df = parse_csv(csv_bytes)
        assert df.iloc[0, 0] == ""
        assert df.iloc[0, 1] == ""


# ---------------------------------------------------------------------------
# extract_lead_data
# ---------------------------------------------------------------------------

class TestExtractLeadData:
    def test_primary_fields(self):
        row = _make_lead_row()
        csv_bytes = _build_csv_bytes([row])
        df = parse_csv(csv_bytes)
        lead = extract_lead_data(df, 0)

        assert lead["first_name"] == "Jane"
        assert lead["last_name"] == "Doe"
        assert lead["organization"] == "Contoso Ltd"
        assert lead["license_renewal"] == "Microsoft 365 E5"
        assert lead["engagement_objectives"] == "Streamline renewal process"
        assert lead["row_index"] == 0

    def test_demographic_columns_included(self):
        row = _make_lead_row()
        csv_bytes = _build_csv_bytes([row])
        df = parse_csv(csv_bytes)
        lead = extract_lead_data(df, 0)

        # Column D (index 3) header → "D", value → "Technology"
        assert lead.get("D") == "Technology"
        # Column E (index 4) header → "E", value → "500-1000"
        assert lead.get("E") == "500-1000"
        # Column AE (index 30) → "CFO"
        assert lead.get("AE") == "CFO"

    def test_skips_primary_columns_in_demographics(self):
        """Primary field column headers should not appear as demographic entries."""
        row = _make_lead_row()
        csv_bytes = _build_csv_bytes([row])
        df = parse_csv(csv_bytes)
        lead = extract_lead_data(df, 0)

        # These are extracted as first_name / last_name / organization etc,
        # so should NOT also appear under their column header keys
        assert "A" not in lead  # license_renewal col
        assert "B" not in lead  # engagement_objectives col
        assert "K" not in lead  # first_name col
        assert "L" not in lead  # last_name col
        assert "W" not in lead  # organization col

    def test_skips_empty_demographic_values(self):
        row = _make_lead_row()
        csv_bytes = _build_csv_bytes([row])
        df = parse_csv(csv_bytes)
        lead = extract_lead_data(df, 0)

        # Column F (index 5) is empty → should not be in the dict
        assert "F" not in lead

    def test_handles_short_csv(self):
        """If the CSV has fewer than 23 columns, missing fields should be empty strings."""
        csv_bytes = b"A,B,C,D,E,F,G,H,I,J,K\nlic,obj,c,d,e,f,g,h,i,j,Jane\n"
        df = parse_csv(csv_bytes)
        lead = extract_lead_data(df, 0)

        assert lead["first_name"] == "Jane"
        assert lead["last_name"] == ""    # col L missing
        assert lead["organization"] == "" # col W missing

    def test_with_explicit_column_map(self):
        """When column_map is provided, use those indices instead of hardcoded ones."""
        csv_bytes = b"Company,GivenName,FamilyName,Product,Goals,Extra\nAcme,Bob,Smith,Azure,Migrate,IT\n"
        df = parse_csv(csv_bytes)
        column_map = {
            "organization": 0,
            "first_name": 1,
            "last_name": 2,
            "license_renewal": 3,
            "engagement_objectives": 4,
        }
        lead = extract_lead_data(df, 0, column_map)
        assert lead["first_name"] == "Bob"
        assert lead["last_name"] == "Smith"
        assert lead["organization"] == "Acme"
        assert lead["license_renewal"] == "Azure"
        assert lead["engagement_objectives"] == "Migrate"
        # Extra column should be in demographics
        assert lead.get("Extra") == "IT"

    def test_column_map_skips_primary_indices(self):
        """Columns used in column_map should not appear as demographics."""
        csv_bytes = b"first_name,last_name,org,license,objective\nAlice,Wonder,Oz,M365,Renew\n"
        df = parse_csv(csv_bytes)
        column_map = {"first_name": 0, "last_name": 1, "organization": 2, "license_renewal": 3, "engagement_objectives": 4}
        lead = extract_lead_data(df, 0, column_map)
        # None of the primary headers should appear as demographic keys
        assert "first_name" not in [k for k in lead if k not in ("row_index", "first_name", "last_name", "organization", "license_renewal", "engagement_objectives")]


# ---------------------------------------------------------------------------
# extract_all_leads
# ---------------------------------------------------------------------------

class TestExtractAllLeads:
    def test_extracts_all_rows(self):
        rows = [_make_lead_row() for _ in range(5)]
        rows[2][10] = "Alice"
        csv_bytes = _build_csv_bytes(rows)
        df = parse_csv(csv_bytes)
        leads = extract_all_leads(df)

        assert len(leads) == 5
        assert leads[0]["row_index"] == 0
        assert leads[2]["first_name"] == "Alice"
        assert leads[4]["row_index"] == 4


# ---------------------------------------------------------------------------
# assemble_enriched_csv
# ---------------------------------------------------------------------------

def _make_email_results(num_rows: int, num_emails: int = 8) -> list[dict]:
    """Generate well-formed email results for the given number of rows."""
    results = []
    for i in range(num_rows):
        emails = [
            {"subject": f"Subject T{t+1} R{i}", "body": f"Body T{t+1} R{i}"}
            for t in range(num_emails)
        ]
        results.append({"row_index": i, "parsed": emails})
    return results


class TestAssembleEnrichedCSV:
    def test_adds_output_columns(self):
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = _make_email_results(1)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert "Subject_Touch1" in df.columns
        assert "Body_Touch8" in df.columns

    def test_correct_values_placed(self):
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = _make_email_results(1)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df["Subject_Touch1"].iloc[0] == "Subject T1 R0"
        assert df["Body_Touch1"].iloc[0] == "Body T1 R0"
        assert df["Subject_Touch8"].iloc[0] == "Subject T8 R0"
        assert df["Body_Touch8"].iloc[0] == "Body T8 R0"

    def test_preserves_original_data(self):
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = _make_email_results(1)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df.iloc[0, 0] == "Microsoft 365 E5"
        assert df.iloc[0, 10] == "Jane"

    def test_multiple_rows(self):
        rows = [_make_lead_row() for _ in range(3)]
        rows[1][10] = "Alice"
        rows[2][10] = "Bob"
        csv_bytes = _build_csv_bytes(rows)
        results = _make_email_results(3)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert len(df) == 3
        assert df["Subject_Touch1"].iloc[1] == "Subject T1 R1"
        assert df["Body_Touch3"].iloc[2] == "Body T3 R2"

    def test_error_result_fills_error_marker(self):
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = [{"row_index": 0, "error": "API timeout"}]
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df["Subject_Touch1"].iloc[0] == "Generation unavailable"
        assert df["Body_Touch8"].iloc[0] == "Generation unavailable for this lead: API timeout"

    def test_content_filter_error_is_sanitized(self):
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        raw_error = "Error code: 400 - {'error': {'code': 'content_filter', 'innererror': {'code': 'ResponsibleAIPolicyViolation'}, 'message': 'https://go.microsoft.com/fwlink/?linkid=2198766'}}"
        results = [{"row_index": 0, "error": raw_error}]
        out_headers = _output_headers(4)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df["Subject_Touch1"].iloc[0] == "Generation unavailable"
        body = df["Body_Touch1"].iloc[0]
        assert "Azure OpenAI blocked this lead" in body
        assert "ResponsibleAIPolicyViolation" not in body
        assert "go.microsoft.com" not in body

    def test_skips_out_of_range_row_index(self):
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = [{"row_index": 99, "parsed": []}]
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df["Subject_Touch1"].iloc[0] == ""

    def test_output_appended_at_end(self):
        """Output columns should be appended after existing columns."""
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = _make_email_results(1)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df.columns[75] == "Subject_Touch1"
        assert df.columns[76] == "Body_Touch1"
        assert df.columns[90] == "Body_Touch8"

    def test_output_appended_for_small_csv(self):
        """For a CSV with only 5 columns, output should start at index 5."""
        csv_bytes = b"A,B,C,D,E\n1,2,3,4,5\n"
        results = _make_email_results(1)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df.columns[5] == "Subject_Touch1"
        assert df.columns[6] == "Body_Touch1"

    def test_4_email_template(self):
        """Test assembly with a 4-email template."""
        csv_bytes = b"Name,Org\nAlice,Acme\n"
        results = _make_email_results(1, num_emails=4)
        out_headers = _output_headers(4)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)

        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert "Subject_Touch1" in df.columns
        assert "Body_Touch4" in df.columns
        assert "Subject_Touch5" not in df.columns


# ---------------------------------------------------------------------------
# Constants validation
# ---------------------------------------------------------------------------

class TestConstants:
    def test_output_start_col_index_legacy(self):
        # Legacy constant kept for backwards compatibility
        assert OUTPUT_START_COL_INDEX == 74


# ---------------------------------------------------------------------------
# assemble_enriched_csv — dynamic output headers / flatten
# ---------------------------------------------------------------------------

class TestAssembleEnrichedCSVDynamic:
    def test_custom_output_headers(self):
        """Custom output headers should appear in the output CSV."""
        csv_bytes = b"Name,Email\nAlice,alice@example.com\n"
        results = [{"row_index": 0, "parsed": [{"greeting": "Hello", "tone": "warm"}]}]
        custom_headers = ["greeting", "tone"]
        flat_fn = lambda parsed: {k: v for item in parsed for k, v in item.items()}

        enriched = assemble_enriched_csv(csv_bytes, results,
                                          output_headers=custom_headers,
                                          flatten_result=flat_fn)
        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert "greeting" in df.columns
        assert "tone" in df.columns
        assert df["greeting"].iloc[0] == "Hello"
        assert df["tone"].iloc[0] == "warm"

    def test_error_fills_all_custom_columns(self):
        """Errors should fill all dynamic output columns."""
        csv_bytes = b"Name\nBob\n"
        results = [{"row_index": 0, "error": "Timeout"}]
        custom_headers = ["col_a", "col_b", "col_c"]

        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=custom_headers)
        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert "Generation unavailable for this lead: Timeout" in df["col_a"].iloc[0]
        assert "Generation unavailable for this lead: Timeout" in df["col_c"].iloc[0]

    def test_legacy_results_with_explicit_headers(self):
        """Results with parsed key work when output_headers and flatten_result are provided."""
        csv_bytes = _build_csv_bytes([_make_lead_row()])
        results = _make_email_results(1)
        out_headers = _output_headers(8)
        enriched = assemble_enriched_csv(csv_bytes, results, output_headers=out_headers, flatten_result=_flatten_emails)
        df = pd.read_csv(io.BytesIO(enriched), dtype=str, keep_default_na=False)
        assert df["Subject_Touch1"].iloc[0] == "Subject T1 R0"

    def test_output_headers_function(self):
        headers = _output_headers(8)
        assert headers[0] == "Subject_Touch1"
        assert headers[1] == "Body_Touch1"
        assert headers[14] == "Subject_Touch8"
        assert headers[15] == "Body_Touch8"


# ---------------------------------------------------------------------------
# parse_file / parse_excel / dataframe_to_csv_bytes
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_parse_file_csv(self):
        csv_bytes = b"A,B,C\n1,2,3\n"
        df = parse_file(csv_bytes, "test.csv")
        assert len(df) == 1
        assert list(df.columns) == ["A", "B", "C"]

    def test_parse_file_xlsx(self, tmp_path):
        """Round-trip: create an xlsx, then parse it."""
        df_original = pd.DataFrame({"Name": ["Alice"], "Age": ["30"]})
        xlsx_path = tmp_path / "test.xlsx"
        df_original.to_excel(xlsx_path, index=False, engine="openpyxl")
        xlsx_bytes = xlsx_path.read_bytes()

        df = parse_file(xlsx_bytes, "test.xlsx")
        assert len(df) == 1
        assert df.iloc[0, 0] == "Alice"

    def test_parse_file_case_insensitive(self, tmp_path):
        df_original = pd.DataFrame({"X": ["1"]})
        xlsx_path = tmp_path / "test.XLSX"
        df_original.to_excel(xlsx_path, index=False, engine="openpyxl")
        xlsx_bytes = xlsx_path.read_bytes()

        df = parse_file(xlsx_bytes, "DATA.XLSX")
        assert len(df) == 1

    def test_dataframe_to_csv_bytes(self):
        df = pd.DataFrame({"A": ["1"], "B": ["2"]})
        csv_bytes = dataframe_to_csv_bytes(df)
        # Should be utf-8-sig (BOM)
        assert csv_bytes[:3] == b"\xef\xbb\xbf"
        df_back = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, encoding="utf-8-sig")
        assert df_back.iloc[0, 0] == "1"
