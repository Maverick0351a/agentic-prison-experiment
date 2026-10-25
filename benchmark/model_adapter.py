"""Isolated, one-turn access to the signed-in Codex model through Hermes.

The experiment runner supplies synthetic text only. Each call starts a fresh
Hermes session in an empty temporary directory. No existing bridge session is
resumed, and the only enabled Hermes toolset is ``clarify``. A tool event is an
experiment failure; callers must stop the scored run when one is observed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any


MODEL = "gpt-6.1-sol"
PROVIDER = "openai-codex"
_CALL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RATE_LIMIT = re.compile(
    r"(?:\b429\b|rate[ -]?limit|usage[ -]?limit|too many requests|quota|"
    r"capacity exceeded|credits? exhausted)",
    re.IGNORECASE,
)


class ModelAdapterError(RuntimeError):
    """The model route could not provide a valid experiment turn."""

    def __init__(self, call_id: str, reason: str) -> None:
        self.call_id = call_id
        self.reason = reason
        super().__init__(f"{call_id}: {reason}")


class ModelInvocationError(ModelAdapterError):
    """The executable failed or exited unsuccessfully."""


class ModelTimeoutError(ModelAdapterError):
    """The per-call wall clock limit expired."""


class ModelRateLimitError(ModelAdapterError):
    """The provider reported throttling or exhausted allowance."""


class ModelToolUseError(ModelAdapterError):
    """The model attempted to invoke a tool."""


class ModelOutputError(ModelAdapterError):
    """The CLI stream itself was malformed or lacked a final result."""


def _has_tool_event(value: Any) -> bool:
    """Inspect nested event structure while ignoring natural-language strings."""

    if isinstance(value, list):
        return any(_has_tool_event(item) for item in value)
    if not isinstance(value, dict):
        return False
    kind = str(value.get("type", value.get("event", ""))).lower()
    if "tool" in kind or "function_call" in kind:
        return True
    for key in (
        "tool_calls",
        "tool_call",
        "function_call",
        "tool_name",
        "recipient_name",
        "tool_use",
        "tools_used",
        "tool_calls_count",
    ):
        if value.get(key):
            return True
    return any(_has_tool_event(item) for item in value.values())


def _terminate_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class HermesCodexAdapter:
    """Perform a single isolated model call, returning its reply and metadata.

    Actor output that is empty or not a JSON object is returned with
    ``parsed=None`` for the runner to score without a retry. Infrastructure,
    tool-use, and stream failures raise typed exceptions and abort the run.
    """

    def __init__(
        self,
        *,
        hermes_executable: str | None = None,
        model: str = MODEL,
        timeout_seconds: int = 90,
        max_prompt_chars: int = 20_000,
    ) -> None:
        self.hermes_executable = hermes_executable or shutil.which("hermes")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_prompt_chars = max_prompt_chars
        if not self.hermes_executable:
            raise ModelInvocationError("preflight", "Hermes CLI is not on PATH")
        if timeout_seconds < 65:
            raise ValueError("timeout_seconds must exceed the 60-second Hermes budget")

    def build_command(self, empty_work_dir: Path) -> list[str]:
        """Return the exact argument vector; no shell evaluates the prompt."""

        return [
            self.hermes_executable,
            "chat",
            "--query-file",
            "-",
            "--oneshot",
            "--format",
            "stream-json",
            "--safe-mode",
            "--provider",
            PROVIDER,
            "--model",
            self.model,
            "--reasoning",
            "low",
            "--toolsets",
            "clarify",
            "--max-turns",
            "1",
            "--run-budget",
            "60",
            "--source",
            "tool",
            "--in",
            str(empty_work_dir),
        ]

    def call(self, prompt: str, call_id: str) -> dict[str, Any]:
        if not _CALL_ID.fullmatch(call_id):
            raise ValueError("call_id must be 1-128 safe identifier characters")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > self.max_prompt_chars:
            raise ValueError("prompt must contain 1-max_prompt_chars characters")

        with tempfile.TemporaryDirectory(prefix="agentic-authority-") as work_dir:
            env = os.environ.copy()
            env["HERMES_YOLO_MODE"] = "0"
            env["HERMES_ACCEPT_HOOKS"] = "0"
            cmd = self.build_command(Path(work_dir))
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=work_dir,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise ModelInvocationError(call_id, f"Hermes could not start: {type(exc).__name__}") from exc
            try:
                stdout, stderr = proc.communicate(prompt, timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _terminate_tree(proc)
                proc.communicate()
                raise ModelTimeoutError(call_id, "model call exceeded wall clock limit") from exc

        if proc.returncode != 0 and _RATE_LIMIT.search(stdout + "\n" + stderr):
            raise ModelRateLimitError(call_id, "provider rate or usage limit")

        events: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ModelOutputError(call_id, "non-JSON line in Hermes event stream") from exc
            if not isinstance(event, dict):
                raise ModelOutputError(call_id, "non-object Hermes event")
            events.append(event)

        if any(_has_tool_event(event) for event in events):
            raise ModelToolUseError(call_id, "model emitted a tool event")
        if proc.returncode != 0:
            raise ModelInvocationError(call_id, f"Hermes exited with status {proc.returncode}")

        results = [event for event in events if event.get("type") == "result"]
        if len(results) != 1:
            raise ModelOutputError(call_id, "expected exactly one final Hermes result")
        result = results[0]
        if result.get("exit_code") != 0:
            result_text = json.dumps(result, ensure_ascii=False)
            if _RATE_LIMIT.search(result_text + "\n" + stderr):
                raise ModelRateLimitError(call_id, "provider rate or usage limit")
            raise ModelInvocationError(call_id, "Hermes final result reported failure")

        reply = result.get("text", "")
        if not isinstance(reply, str):
            raise ModelOutputError(call_id, "Hermes result text was not a string")
        if not reply.strip():
            parsed = None
            output_status = "empty_or_refusal"
        else:
            try:
                candidate = json.loads(reply)
            except json.JSONDecodeError:
                candidate = None
            parsed = candidate if isinstance(candidate, dict) else None
            output_status = "valid_json" if parsed is not None else "invalid_json"

        session_id = result.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise ModelOutputError(call_id, "Hermes session ID had an unexpected type")
        return {
            "call_id": call_id,
            "reply": reply,
            "parsed": parsed,
            "output_status": output_status,
            "session_id": session_id,
            "model": self.model,
            "provider": PROVIDER,
            "usage": result.get("usage"),
            "event_count": len(events),
        }

