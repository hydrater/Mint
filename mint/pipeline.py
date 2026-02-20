from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agents import ExecutionAgent, SummaryAgent
from .google_sheet import GoogleSheetClient, TASK_START_ROW


def _join_prefix(prefix: str, prompt: str) -> str:
    prefix = prefix.strip()
    prompt = prompt.strip()
    if not prefix:
        return prompt
    if not prompt:
        return prefix
    return f"{prefix} {prompt}"


@dataclass(slots=True)
class RunSummary:
    executed_rows: int
    archived_rows: int
    stopped_at_row: int


class MintPipeline:
    def __init__(
        self,
        sheet_client: GoogleSheetClient,
        config: dict[str, Any],
    ) -> None:
        self.sheet_client = sheet_client
        self.config = config
        self.summary_agent = SummaryAgent()

    def run(self, sheet_url: str) -> RunSummary:
        spreadsheet_id = self._spreadsheet_id(sheet_url)
        props = self.sheet_client.get_properties(spreadsheet_id)

        prefix = props["prefix"] or self.config["sheet_properties"].get("prefix", "")
        command = props["command"] or self.config["sheet_properties"].get("command", "")
        auto_close = self._resolve_bool(
            props.get("auto_close", ""),
            self.config["sheet_properties"].get("auto_close", True),
        )
        execution_agent = ExecutionAgent(auto_close_after_task=auto_close)
        if not command:
            raise ValueError(
                "Command is empty. Fill A5 in the sheet or run: mint setup command \"<cmd>\""
            )

        row_number = TASK_START_ROW
        executed_rows = 0
        archived_rows = 0

        while True:
            row = self.sheet_client.read_row(spreadsheet_id, row_number)

            if not row.prompt:
                return RunSummary(
                    executed_rows=executed_rows,
                    archived_rows=archived_rows,
                    stopped_at_row=row_number,
                )

            status = (row.status or "").strip()

            if status == "Approved":
                print(f"Row {row_number}: Approved -> archiving.")
                self.sheet_client.archive_and_shift(spreadsheet_id, row_number)
                archived_rows += 1
                continue

            if not row.ticket:
                print(f"Row {row_number}: New task found -> running agent.")
                summary = self.summary_agent.summarize(row.prompt)
                self.sheet_client.update_row_columns(
                    spreadsheet_id,
                    row_number,
                    {"C": summary, "D": "Ongoing"},
                )
                result = execution_agent.run(
                    command=command,
                    prompt=_join_prefix(prefix, row.prompt),
                )
                updates = {
                    "D": result.status,
                    "F": result.thoughts,
                }
                if result.session_id:
                    updates["G"] = result.session_id
                self.sheet_client.update_row_columns(spreadsheet_id, row_number, updates)
                executed_rows += 1
                row_number += 1
                continue

            if status == "Ongoing":
                print(f"Row {row_number}: Ongoing -> resuming task.")
                resume_prompt = (row.user_input or "").strip() or row.prompt
                result = execution_agent.run(
                    command=command,
                    prompt=_join_prefix(prefix, resume_prompt),
                    session_id=row.session_id,
                )
                updates = {
                    "D": result.status,
                    "F": result.thoughts,
                }
                if result.session_id:
                    updates["G"] = result.session_id
                self.sheet_client.update_row_columns(spreadsheet_id, row_number, updates)
                executed_rows += 1

            row_number += 1

    @staticmethod
    def _spreadsheet_id(sheet_url: str) -> str:
        from .google_sheet import parse_sheet_id

        return parse_sheet_id(sheet_url)

    @staticmethod
    def _resolve_bool(value: Any, fallback: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(fallback)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
        return bool(fallback)
