"""CSV / Excel parsing and assembly utilities for the Email MVP."""

import io
import re
import pandas as pd


# Legacy constant kept for backwards compatibility with old tests/code
OUTPUT_START_COL_INDEX = 74


def _excel_col_letter(index: int) -> str:
    """Convert a 0-based column index to Excel-style letter(s). e.g. 0->A, 25->Z, 26->AA."""
    result = ""
    while True:
        result = chr(index % 26 + ord("A")) + result
        index = index // 26 - 1
        if index < 0:
            break
    return result


def parse_csv(csv_bytes: bytes) -> pd.DataFrame:
    """Parse raw CSV bytes into a DataFrame, preserving all columns."""
    return pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False)


def parse_excel(excel_bytes: bytes) -> pd.DataFrame:
    """Parse raw .xlsx bytes into a DataFrame, preserving all columns."""
    return pd.read_excel(io.BytesIO(excel_bytes), dtype=str, keep_default_na=False, engine="openpyxl")


def parse_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Parse CSV or Excel bytes based on the filename extension."""
    if filename.lower().endswith(".xlsx"):
        return parse_excel(file_bytes)
    return parse_csv(file_bytes)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convert a DataFrame to CSV bytes (utf-8-sig encoded)."""
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def extract_lead_data(df: pd.DataFrame, row_index: int, column_map: dict | None = None) -> dict:
    """Extract a single lead's data from a DataFrame row.

    If column_map is provided, it maps field names to column indices:
      {"first_name": idx, "last_name": idx, "organization": idx,
       "license_renewal": idx, "engagement_objectives": idx}

    If column_map is None, falls back to legacy hardcoded positions:
      - Column A (index 0)  -> license_renewal
      - Column B (index 1)  -> engagement_objectives
      - Column K (index 10) -> first_name
      - Column L (index 11) -> last_name
      - Column W (index 22) -> organization
    """
    row = df.iloc[row_index]
    headers = df.columns.tolist()

    if column_map is None:
        # Legacy hardcoded mapping
        column_map = {
            "license_renewal": 0,
            "engagement_objectives": 1,
            "first_name": 10,
            "last_name": 11,
            "organization": 22,
        }

    primary_indices = set(column_map.values())

    lead = {"row_index": row_index}
    for field, idx in column_map.items():
        lead[field] = str(row.iloc[idx]) if len(headers) > idx else ""

    # Add all remaining columns as demographic/psychographic data
    for col_idx in range(len(headers)):
        if col_idx in primary_indices:
            continue
        header = headers[col_idx]
        # Skip output columns from previously enriched CSVs
        if re.match(r'^(Subject|Body)_Touch\d+$', header):
            continue
        value = str(row.iloc[col_idx])
        if value.strip():
            lead[header] = value

    return lead


def extract_all_leads(df: pd.DataFrame, column_map: dict | None = None) -> list[dict]:
    """Extract lead data for every row in the DataFrame."""
    return [extract_lead_data(df, i, column_map) for i in range(len(df))]


def assemble_enriched_csv(
    original_csv_bytes: bytes,
    results: list[dict],
    output_headers: list[str] | None = None,
    flatten_result=None,
) -> bytes:
    """Merge generated data back into the original CSV.

    Output columns are appended at the end of the existing columns.

    Args:
        original_csv_bytes: The raw bytes of the uploaded CSV.
        results: List of dicts, each with 'row_index' and 'parsed' (pre-parsed data)
                 or 'error' for failed rows.
        output_headers: List of column header names for output.
        flatten_result: Callable that converts parsed data to {header: value} dict.

    Returns:
        Enriched CSV as bytes.
    """
    df = parse_csv(original_csv_bytes)

    out_headers = output_headers or []
    total_out_cols = len(out_headers)

    # Determine where to start writing — append after the last existing column
    output_start = len(df.columns)

    # Add output columns
    for header in out_headers:
        df[header] = ""

    # Fill in the generated data
    for result in results:
        row_idx = result.get("row_index")
        if row_idx is None or row_idx >= len(df):
            continue

        error = result.get("error")

        if error:
            for i in range(total_out_cols):
                df.iloc[row_idx, output_start + i] = f"[ERROR: {error}]"
        elif flatten_result and "parsed" in result:
            flat = flatten_result(result["parsed"])
            for col_name, value in flat.items():
                if col_name in df.columns:
                    df.at[row_idx, col_name] = value
        else:
            for i in range(total_out_cols):
                df.iloc[row_idx, output_start + i] = "[ERROR: Invalid response format]"

    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()
