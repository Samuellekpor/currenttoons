"""Thin Google Sheets helpers (gspread)."""

from __future__ import annotations

import os
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
)


def _client(credentials_path: str | None = None) -> gspread.Client:
    path = credentials_path or os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH")
    if not path:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS_PATH is not set")
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(sheet_id: str, *, credentials_path: str | None = None):
    return _client(credentials_path).open_by_key(sheet_id)


def open_worksheet(sheet_id: str, tab: str, *, credentials_path: str | None = None):
    return open_spreadsheet(sheet_id, credentials_path=credentials_path).worksheet(tab)


def ensure_headers(
    sheet_id: str,
    tab: str,
    headers: list[str],
    *,
    credentials_path: str | None = None,
):
    spreadsheet = open_spreadsheet(sheet_id, credentials_path=credentials_path)
    try:
        ws = spreadsheet.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab, rows=2000, cols=max(len(headers), 12))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws
    existing = ws.row_values(1)
    if not existing:
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws
    missing = [h for h in headers if h not in existing]
    if missing:
        start_col = len(existing) + 1
        for offset, name in enumerate(missing):
            ws.update_cell(1, start_col + offset, name)
    return ws


def existing_column_values(
    sheet_id: str,
    tab: str,
    column_name: str,
    *,
    credentials_path: str | None = None,
) -> set[str]:
    ws = open_worksheet(sheet_id, tab, credentials_path=credentials_path)
    records = ws.get_all_records()
    return {str(row.get(column_name, "")).strip() for row in records if row.get(column_name)}


def increment_numeric_cell(
    sheet_id: str,
    *,
    row_key: str,
    column_name: str,
    delta: float,
    tab: str = "Vidéos",
    key_column: str = "Titre",
    credentials_path: str | None = None,
) -> float:
    ws = open_worksheet(sheet_id, tab, credentials_path=credentials_path)
    records = ws.get_all_records()
    headers = ws.row_values(1)
    if column_name not in headers:
        raise ValueError(f"Missing column {column_name!r} in sheet {sheet_id}")
    col_index = headers.index(column_name) + 1
    for i, row in enumerate(records, start=2):
        if str(row.get(key_column, "")) == str(row_key):
            current = row.get(column_name) or 0
            try:
                current_f = float(str(current).replace(",", ".").replace("€", "").strip() or 0)
            except ValueError:
                current_f = 0.0
            new_value = round(current_f + delta, 4)
            ws.update_cell(i, col_index, new_value)
            return new_value
    raise KeyError(f"Row {row_key!r} not found in column {key_column}")


def upsert_record(
    sheet_id: str,
    tab: str,
    *,
    match_column: str,
    match_value: str,
    values: dict[str, Any],
    credentials_path: str | None = None,
) -> dict[str, Any]:
    ws = open_worksheet(sheet_id, tab, credentials_path=credentials_path)
    headers = ws.row_values(1)
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get(match_column, "")).strip().lower() == match_value.strip().lower():
            for key, value in values.items():
                if key in headers:
                    ws.update_cell(i, headers.index(key) + 1, value)
            return {**row, **values, "_row": i, "_created": False}
    new_row = [values.get(h, "") for h in headers]
    ws.append_row(new_row, value_input_option="USER_ENTERED")
    return {**values, "_created": True}
