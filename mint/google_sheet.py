from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from google.auth.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

HEADERS = [
    "Configs",
    "User Prompt",
    "Ticket Summary",
    "Status",
    "User Input",
    "AI Thoughts / Output",
    "Session ID",
    "",
    "",
    "Approved Tickets",
    "Original Prompt",
    "Final Thoughts",
]

STATUS_OPTIONS = ["Ongoing", "Testing", "Blocked", "Completed", "Approved"]
TASK_START_ROW = 2
MAX_ROWS = 2000
CONFIG_START_ROW = 2
CONFIG_PROPERTIES: list[tuple[str, str]] = [
    ("prefix", "Prefix"),
    ("command", "Command"),
    ("auto_close", "Auto Close"),
]


def _config_total_rows() -> int:
    return len(CONFIG_PROPERTIES) * 2


def _config_end_row() -> int:
    return CONFIG_START_ROW + _config_total_rows() - 1


def _single_line(value: str) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def parse_sheet_id(sheet_url: str) -> str:
    sheet_url = sheet_url.strip()
    if "/" not in sheet_url and re.fullmatch(r"[a-zA-Z0-9-_]+", sheet_url):
        return sheet_url
    pattern = r"/spreadsheets/d/([a-zA-Z0-9-_]+)"
    match = re.search(pattern, sheet_url)
    if not match:
        raise ValueError(f"Invalid Google Sheet URL: {sheet_url}")
    return match.group(1)


def to_sheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


@dataclass(slots=True)
class RowState:
    prompt: str
    ticket: str
    status: str
    user_input: str
    thoughts: str
    session_id: str


class GoogleSheetClient:
    def __init__(self, credentials: Credentials) -> None:
        self.sheets = build("sheets", "v4", credentials=credentials)

    def verify_access(self, spreadsheet_id: str) -> None:
        try:
            self.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        except HttpError as exc:
            raise RuntimeError(
                "Unable to access spreadsheet. Make sure the sheet is shared "
                "with your service account email."
            ) from exc

    def initialize_layout(
        self,
        spreadsheet_id: str,
        property_values: dict[str, Any] | None = None,
    ) -> None:
        meta = self.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        first_sheet = meta["sheets"][0]["properties"]
        sheet_id = first_sheet["sheetId"]
        property_values = property_values or {}

        self.sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="A1:L1",
            valueInputOption="USER_ENTERED",
            body={"values": [HEADERS]},
        ).execute()

        config_cells: list[list[str]] = []
        for key, title in CONFIG_PROPERTIES:
            raw_value = property_values.get(key, "")
            value = str(raw_value).lower() if isinstance(raw_value, bool) else str(raw_value or "")
            config_cells.append([title])
            config_cells.append([value])

        self.sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"A{CONFIG_START_ROW}:A{_config_end_row()}",
            valueInputOption="USER_ENTERED",
            body={"values": config_cells},
        ).execute()

        requests: list[dict[str, Any]] = [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(HEADERS),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "CLIP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 0,  # A
                        "endColumnIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "verticalAlignment": "TOP",
                        }
                    },
                    "fields": "userEnteredFormat.verticalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 1,  # B
                        "endColumnIndex": 2,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 5,  # F
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "verticalAlignment": "TOP",
                        }
                    },
                    "fields": "userEnteredFormat.verticalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 5,  # F
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 9,  # J
                        "endColumnIndex": 12,  # L
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "CLIP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": CONFIG_START_ROW - 1,
                        "endRowIndex": _config_end_row(),
                        "startColumnIndex": 0,
                        "endColumnIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "LEFT",
                            "textFormat": {"bold": False},
                        }
                    },
                    "fields": "userEnteredFormat.horizontalAlignment,userEnteredFormat.textFormat.bold",
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 3,
                        "endColumnIndex": 4,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": item} for item in STATUS_OPTIONS],
                        },
                        "showCustomUi": True,
                        "strict": True,
                    },
                }
            },
        ]

        for index, _ in enumerate(CONFIG_PROPERTIES):
            title_row = CONFIG_START_ROW + (index * 2)
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": title_row - 1,
                            "endRowIndex": title_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                            }
                        },
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                }
            )
        self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()

    def get_properties(self, spreadsheet_id: str) -> dict[str, str]:
        values = self.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"A{CONFIG_START_ROW}:A{_config_end_row()}",
        ).execute().get("values", [])
        padded = [row[0] if row else "" for row in values]
        while len(padded) < _config_total_rows():
            padded.append("")
        properties: dict[str, str] = {}
        for index, (key, _) in enumerate(CONFIG_PROPERTIES):
            value_index = index * 2 + 1
            properties[key] = padded[value_index]
        return properties

    def enforce_runtime_layout(self, spreadsheet_id: str) -> None:
        meta = self.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        first_sheet = meta["sheets"][0]["properties"]
        sheet_id = first_sheet["sheetId"]

        requests: list[dict[str, Any]] = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 0,  # A
                        "endColumnIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "verticalAlignment": "TOP",
                        }
                    },
                    "fields": "userEnteredFormat.verticalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 5,  # F
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "verticalAlignment": "TOP",
                        }
                    },
                    "fields": "userEnteredFormat.verticalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 1,  # B
                        "endColumnIndex": 2,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 5,  # F
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": MAX_ROWS,
                        "startColumnIndex": 9,  # J
                        "endColumnIndex": 12,  # L
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "CLIP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
        ]

        self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()

    def normalize_column_l_single_line(self, spreadsheet_id: str) -> None:
        values = self.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"L2:L{MAX_ROWS}",
        ).execute().get("values", [])

        updates: list[dict[str, Any]] = []
        for row_offset, row_values in enumerate(values):
            if not row_values:
                continue
            original = str(row_values[0] or "")
            normalized = _single_line(original)
            if normalized == original:
                continue
            row_number = 2 + row_offset
            updates.append(
                {
                    "range": f"L{row_number}",
                    "values": [[normalized]],
                }
            )

        if not updates:
            return

        self.sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": updates,
            },
        ).execute()

    def read_row(self, spreadsheet_id: str, row: int) -> RowState:
        values = self.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"A{row}:L{row}",
        ).execute().get("values", [])
        row_values = values[0] if values else []
        row_values += [""] * (12 - len(row_values))
        return RowState(
            prompt=row_values[1],
            ticket=row_values[2],
            status=row_values[3],
            user_input=row_values[4],
            thoughts=row_values[5],
            session_id=row_values[6],
        )

    def update_row_columns(
        self,
        spreadsheet_id: str,
        row: int,
        updates: dict[str, str],
    ) -> None:
        if not updates:
            return
        data = []
        for column, value in updates.items():
            data.append(
                {
                    "range": f"{column.upper()}{row}",
                    "values": [[value]],
                }
            )
        self.sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": data,
            },
        ).execute()

    def archive_and_shift(self, spreadsheet_id: str, row: int) -> None:
        state = self.read_row(spreadsheet_id, row)
        self.update_row_columns(
            spreadsheet_id,
            row,
            {
                "J": state.ticket,
                "K": state.prompt,
                "L": _single_line(state.thoughts),
            },
        )

        tail_values = self.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"A{row + 1}:G",
        ).execute().get("values", [])

        b_to_g_rows: list[list[str]] = []
        for item in tail_values:
            padded = item + [""] * (7 - len(item))
            col_a = padded[0]
            cols_b_to_g = padded[1:7]
            if not col_a and not any(cols_b_to_g):
                break
            b_to_g_rows.append(cols_b_to_g)

        if b_to_g_rows:
            destination_end_row = row + len(b_to_g_rows) - 1
            self.sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"B{row}:G{destination_end_row}",
                valueInputOption="USER_ENTERED",
                body={"values": b_to_g_rows},
            ).execute()
            clear_row = destination_end_row + 1
            self.sheets.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"B{clear_row}:G{clear_row}",
                body={},
            ).execute()
        else:
            self.sheets.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"B{row}:G{row}",
                body={},
            ).execute()
