from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ExecutionResult:
    status: str
    thoughts: str
    session_id: str
    return_code: int


class SummaryAgent:
    """Creates compact ticket summaries from user prompts."""

    def summarize(self, prompt: str) -> str:
        clean = " ".join(prompt.split())
        if not clean:
            return ""
        if len(clean) <= 96:
            return clean
        return clean[:93].rstrip() + "..."


class StatusAgent:
    """Maps command output to one of the sheet dropdown statuses."""

    def decide(self, return_code: int, output: str) -> str:
        if return_code != 0:
            return "Blocked"

        normalized = output.lower()
        if "status: testing" in normalized:
            return "Testing"
        if "status: blocked" in normalized:
            return "Blocked"
        if "status: completed" in normalized:
            return "Completed"
        return "Completed"

    def extract_session_id(self, output: str) -> str:
        patterns = [
            r'"session_id"\s*:\s*"([A-Za-z0-9._:-]+)"',
            r"'session_id'\s*:\s*'([A-Za-z0-9._:-]+)'",
            r"/sessions/([A-Za-z0-9._:-]+)",
            r"\bcodex\s+resume\s+([A-Za-z0-9._:-]+)",
            r"\bresume\s+([0-9a-f]{8}-[0-9a-f-]{27,})",
            r"(?:session[_\s-]?id)\s*[:=]\s*([A-Za-z0-9._-]+)",
            r"(?:conversation[_\s-]?id)\s*[:=]\s*([A-Za-z0-9._-]+)",
            r"\bsession\s+([A-Za-z0-9._:-]{8,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, output, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""


class ExecutionAgent:
    """Runs the configured agent command for new or resumed tasks."""

    def __init__(self, timeout_seconds: int = 60 * 60, auto_close_after_task: bool = True) -> None:
        self.timeout_seconds = timeout_seconds
        self.auto_close_after_task = auto_close_after_task
        self.status_agent = StatusAgent()

    def run(self, command: str, prompt: str, session_id: str = "") -> ExecutionResult:
        built = self._build_command(command=command, prompt=prompt, session_id=session_id)
        pre_session_id = self._latest_codex_session_id()

        if self._command_prefers_tty(built):
            return self._run_with_tty(
                built=built,
                session_id=session_id,
                pre_session_id=pre_session_id,
            )

        try:
            return_code, output = self._run_streaming(built)
            if self._requires_tty_fallback(return_code, output):
                return self._run_with_tty(
                    built=built,
                    session_id=session_id,
                    pre_session_id=pre_session_id,
                )
            status = self.status_agent.decide(return_code, output)
            extracted_session = self.status_agent.extract_session_id(output)
            post_session_id = self._latest_codex_session_id()
            if not extracted_session and post_session_id and post_session_id != pre_session_id:
                extracted_session = post_session_id
            thoughts = output
            session_for_message = extracted_session or session_id
            if not session_for_message and post_session_id and post_session_id != pre_session_id:
                session_for_message = post_session_id
            if session_for_message:
                codex_message = self._latest_codex_assistant_message(session_for_message)
                if codex_message:
                    thoughts = codex_message
        except subprocess.TimeoutExpired:
            thoughts = "Command timed out. Marked as Blocked."
            status = "Blocked"
            extracted_session = ""
            return_code = 124

        return ExecutionResult(
            status=status,
            thoughts=self._truncate(thoughts),
            session_id=extracted_session or session_id,
            return_code=return_code,
        )

    def _run_streaming(self, built: str) -> tuple[int, str]:
        proc = subprocess.Popen(
            built,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        collected: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                collected.append(line.rstrip("\n"))
            return_code = proc.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise

        output = "\n".join(collected).strip() or "(No output)"
        return return_code, output

    def _run_with_tty(
        self,
        built: str,
        session_id: str,
        pre_session_id: str = "",
    ) -> ExecutionResult:
        try:
            completed = subprocess.run(
                built,
                shell=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            post_session_id = self._latest_codex_session_id()
            detected_session_id = self._pick_session_id(
                previous=pre_session_id,
                latest=post_session_id,
                fallback=session_id,
            )
            if completed.returncode == 0:
                output = "Command completed in terminal mode."
            else:
                output = f"Command exited with code {completed.returncode} in terminal mode."
            if detected_session_id:
                output += f"\nSession ID: {detected_session_id}"
            status = self.status_agent.decide(completed.returncode, output)
            thoughts = output
            if detected_session_id:
                codex_message = self._latest_codex_assistant_message(detected_session_id)
                if codex_message:
                    thoughts = codex_message
            return ExecutionResult(
                status=status,
                thoughts=self._truncate(thoughts),
                session_id=detected_session_id,
                return_code=completed.returncode,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status="Blocked",
                thoughts="Command timed out in TTY mode. Marked as Blocked.",
                session_id=session_id,
                return_code=124,
            )

    @staticmethod
    def _requires_tty_fallback(return_code: int, output: str) -> bool:
        if return_code == 0:
            return False
        normalized = output.lower()
        patterns = [
            "stdin is not a terminal",
            "stdin is not a tty",
            "stdout is not a terminal",
            "stdout is not a tty",
            "not a terminal",
            "not a tty",
        ]
        return any(pattern in normalized for pattern in patterns)

    @staticmethod
    def _command_prefers_tty(built_command: str) -> bool:
        text = built_command.strip().lower()
        if ExecutionAgent._is_noninteractive_agent_command(text):
            return False
        return len(text.split()) == 1

    @staticmethod
    def _is_noninteractive_agent_command(text: str) -> bool:
        tokens = text.split()
        if not tokens:
            return False
        return "exec" in tokens or "review" in tokens

    @staticmethod
    def _pick_session_id(previous: str, latest: str, fallback: str) -> str:
        if latest and latest != previous:
            return latest
        if fallback:
            return fallback
        return latest

    @staticmethod
    def _latest_codex_session_id() -> str:
        latest_file = ExecutionAgent._latest_codex_session_file()
        if latest_file is None:
            return ""
        match = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
            latest_file.name,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else ""

    @staticmethod
    def _latest_codex_session_file() -> Path | None:
        root = Path.home() / ".codex" / "sessions"
        if not root.exists():
            return None
        latest_file: Path | None = None
        latest_mtime = -1.0
        for path in root.rglob("rollout-*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_file = path
        return latest_file

    @staticmethod
    def _find_codex_session_file_by_id(session_id: str) -> Path | None:
        if not session_id:
            return None
        root = Path.home() / ".codex" / "sessions"
        if not root.exists():
            return None
        for path in root.rglob(f"*{session_id}.jsonl"):
            return path
        return None

    @staticmethod
    def _extract_assistant_message_from_session_file(path: Path) -> str:
        latest_message = ""
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    record_type = record.get("type")
                    payload = record.get("payload", {})
                    if not isinstance(payload, dict):
                        continue

                    if record_type == "event_msg":
                        if payload.get("type") == "agent_message":
                            msg = payload.get("message")
                            if isinstance(msg, str) and msg.strip():
                                latest_message = msg.strip()
                        elif payload.get("type") == "task_complete":
                            msg = payload.get("last_agent_message")
                            if isinstance(msg, str) and msg.strip():
                                latest_message = msg.strip()

                    if record_type == "response_item":
                        if payload.get("type") == "message" and payload.get("role") == "assistant":
                            content = payload.get("content", [])
                            if isinstance(content, list):
                                for item in content:
                                    if not isinstance(item, dict):
                                        continue
                                    if item.get("type") != "output_text":
                                        continue
                                    text = item.get("text")
                                    if isinstance(text, str) and text.strip():
                                        latest_message = text.strip()
        except OSError:
            return ""
        return latest_message

    def _latest_codex_assistant_message(self, session_id: str = "") -> str:
        target = self._find_codex_session_file_by_id(session_id)
        if target is None:
            target = self._latest_codex_session_file()
        if target is None:
            return ""
        return self._extract_assistant_message_from_session_file(target)

    @staticmethod
    def _escape(prompt: str) -> str:
        return prompt.replace('"', '\\"')

    def _build_command(self, command: str, prompt: str, session_id: str) -> str:
        escaped_prompt = self._escape(prompt)
        if "{prompt}" in command:
            built = command.replace("{prompt}", escaped_prompt)
            if "{session_id}" in built:
                built = built.replace("{session_id}", session_id)
            elif session_id:
                built = f'{built} resume {session_id}'
            return built

        if (
            self.auto_close_after_task
            and not self._is_noninteractive_agent_command(command.strip().lower())
        ):
            if session_id:
                return f'{command} exec resume {session_id} "{escaped_prompt}"'
            return f'{command} exec "{escaped_prompt}"'

        if session_id:
            return f'{command} resume {session_id} "{escaped_prompt}"'
        return f'{command} "{escaped_prompt}"'

    @staticmethod
    def _truncate(text: str, limit: int = 49000) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 15] + "\n...[truncated]"
