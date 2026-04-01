"""CSV / Excel parsing and assembly utilities for the Email MVP."""

import io
import pandas as pd


NUM_TOUCHES = 8
COLS_PER_TOUCH = 2  # Subject + Body
TOTAL_OUTPUT_COLS = NUM_TOUCHES * COLS_PER_TOUCH  # 16

# Legacy constant kept for backwards compatibility with old tests/code
OUTPUT_START_COL_INDEX = 74

# Column header names for the 16 output columns
OUTPUT_HEADERS = []
for i in range(1, NUM_TOUCHES + 1):
    OUTPUT_HEADERS.append(f"Subject_Touch{i}")
    OUTPUT_HEADERS.append(f"Body_Touch{i}")


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
        # Skip output columns if they already exist
        if header in OUTPUT_HEADERS:
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
) -> bytes:
    """Merge generated email data back into the original CSV.

    Output columns are appended at the end of the existing columns.

    Args:
        original_csv_bytes: The raw bytes of the uploaded CSV.
        results: List of dicts, each with 'row_index' and 'emails' (list of 8 {subject, body} dicts).
                 A result may also have 'error' instead of 'emails' for failed rows.

    Returns:
        Enriched CSV as bytes.
    """
    df = parse_csv(original_csv_bytes)

    # Determine where to start writing — append after the last existing column
    output_start = len(df.columns)

    # Add output columns
    for header in OUTPUT_HEADERS:
        df[header] = ""

    # Fill in the generated emails
    for result in results:
        row_idx = result.get("row_index")
        if row_idx is None or row_idx >= len(df):
            continue

        emails = result.get("emails")
        error = result.get("error")

        if error:
            for i in range(TOTAL_OUTPUT_COLS):
                df.iloc[row_idx, output_start + i] = f"[ERROR: {error}]"
        elif emails and len(emails) == NUM_TOUCHES:
            for touch_idx, email in enumerate(emails):
                subject_col = output_start + (touch_idx * 2)
                body_col = output_start + (touch_idx * 2) + 1
                df.iloc[row_idx, subject_col] = email.get("subject", "")
                df.iloc[row_idx, body_col] = email.get("body", "")
        else:
            for i in range(TOTAL_OUTPUT_COLS):
                df.iloc[row_idx, output_start + i] = "[ERROR: Invalid response format]"

    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()
