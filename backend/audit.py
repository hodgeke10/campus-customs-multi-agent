"""Append-only audit trail for the Campus Customs agent team.

Every agent-loop step lands in `output/audit_trail.json` as one JSON object per
line (JSON Lines), so runs accumulate instead of overwriting each other and a
crash mid-run cannot corrupt what is already written.

What gets recorded, per step: when, which run, which ticket, which agent, what
kind of step (run start/end, delegation, tool call, approval), the arguments,
and a short result — enough to reconstruct afterwards who asked for what, which
tool answered, and whether money was ever touched.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"

_MAX_RESULT_CHARS = 1200


def new_run_id() -> str:
    """A short id tying every step of one ticket run together."""
    return uuid.uuid4().hex[:12]


def _shorten(value: Any) -> Any:
    """Keep results readable without losing what matters for an audit."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= _MAX_RESULT_CHARS:
        return json.loads(text) if not isinstance(value, str) else text
    return text[:_MAX_RESULT_CHARS] + f"... [truncated, {len(text)} chars]"


# Steps whose result is the record itself and must never be truncated. A
# Boss decision runs well past the usual cap, and clipping it to a string loses
# the structure the board reads back when you revisit a ticket.
_KEEP_WHOLE = {"run_finished", "run_failed"}


def record(
    run_id: str,
    step: str,
    actor: str,
    ticket_id: int | None = None,
    target: str | None = None,
    detail: Any = None,
    result: Any = None,
) -> None:
    """Append one step. Never raises — auditing must not break a run."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "ticket_id": ticket_id,
        "step": step,
        "actor": actor,
        "target": target,
        "detail": _shorten(detail),
        "result": result if step in _KEEP_WHOLE else _shorten(result),
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Append-only, one object per line, flushed per step so a crash keeps
        # everything written up to that point.
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as exc:  # pragma: no cover - auditing is best effort
        print(f"[audit] could not write step {step!r}: {exc}")


def read_all() -> list[dict]:
    """Every step ever recorded, oldest first."""
    if not AUDIT_PATH.exists():
        return []
    out = []
    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def runs() -> list[dict]:
    """Summary of each run in the trail, for the dashboard."""
    by_run: dict[str, dict] = {}
    for e in read_all():
        r = by_run.setdefault(
            e["run_id"],
            {"run_id": e["run_id"], "ticket_id": e.get("ticket_id"),
             "started": e["ts"], "steps": 0, "agents": set(), "tools": []},
        )
        r["steps"] += 1
        r["ended"] = e["ts"]
        if e.get("actor"):
            r["agents"].add(e["actor"])
        if e["step"] == "tool_call" and e.get("target"):
            r["tools"].append(e["target"])
    for r in by_run.values():
        r["agents"] = sorted(r["agents"])
    return sorted(by_run.values(), key=lambda r: r["started"])
