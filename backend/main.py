"""FastAPI backend for the Campus Customs dashboard.

The React board calls these routes. Shop facts and shop writes go through the
MCP server (`campus-customs-ops`) over `data/campus_customs_new.db` — this
module does not query the shop tables itself, so there is only ever one tools
layer.

The one exception is `/reset`, which copies the pristine master file over the
working copy. That is a file operation on the database, not a shop fact, so it
has no business being an MCP tool.

Run from this folder:  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import audit
from config import MODEL_NAME, PROJECT
from models import Role
from team import ask, build_team, run_ticket

MCP_DIR = PROJECT / "mcp_server"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

# Approvals that move money out of an account. Everything else a human approves
# (a discount, a purchase order) is a commitment, not a payment.
PAYMENT_KINDS = {"invoice", "rent"}

MASTER_DB = PROJECT / "data" / "campus_customs.db"
WORKING_DB = PROJECT / "data" / "campus_customs_new.db"

# Runs in flight or finished this process, keyed by run_id.
RUNS: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the agent team once at startup rather than per request."""
    build_team()
    yield


app = FastAPI(title="Campus Customs Operations", version="1.0", lifespan=lifespan)

# The board is served by Vite and calls these routes straight from the browser,
# so its origin has to be allowed explicitly. 5173 is Vite's default; this
# project runs on 5178 because the lecture apps hold 5173-5177, so the whole
# local dev range is permitted rather than one hard-coded port.
VITE_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in range(5173, 5180)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=VITE_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def tool(name: str, **kwargs) -> dict:
    """Call an MCP tool. Every shop read and write in this file goes through here."""
    import server  # the FastMCP module; path set above

    fn = getattr(server, name, None)
    if fn is None:
        raise HTTPException(500, f"No MCP tool named {name!r}.")
    return fn(**kwargs)


# ----------------------------------------------------------------- board


@app.get("/tickets")
def list_tickets() -> dict:
    """The three tickets and whether each is open or resolved."""
    result = tool("list_tickets", status="all")
    tickets = [
        {
            "id": t["id"],
            "type": t["type"],
            "requester": t["requester"],
            "subject": t["subject"],
            "sku": t["sku"],
            "size": t["size"],
            "qty": t["qty"],
            "status": t["status"],
            "is_open": t["status"] != "resolved",
            "notes": t["notes"],
            "created_at": t["created_at"],
        }
        for t in result["tickets"]
    ]
    return {
        "shop_today": result["shop_today"],
        "count": len(tickets),
        "open_count": sum(1 for t in tickets if t["is_open"]),
        "tickets": tickets,
    }


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> dict:
    """One ticket with every row it links to."""
    result = tool("get_ticket", ticket_id=ticket_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ------------------------------------------------------------- agent run


class RunRequest(BaseModel):
    instruction: str = Field(default="", description="Optional override for the Boss.")


def _dependent_tickets(approval: dict) -> list[int]:
    """Every ticket that depends on the obligation this approval settles.

    One invoice can block several tickets — invoice 501 blocks both the tee
    order and the hoodie restock — so a single approval covers all of them and
    the decision has to reach each one.
    """
    ids: list[int] = []
    if approval.get("ticket_id"):
        ids.append(approval["ticket_id"])
    ref = approval.get("ref_id")
    if ref is not None:
        column = {"invoice": "invoice_id", "rent": "lease_id"}.get(approval["kind"])
        if column:
            for row in tool("list_tickets", status="all")["tickets"]:
                if row.get(column) == ref and row["id"] not in ids:
                    ids.append(row["id"])
    return ids


def _settle_status(ticket_id: int, decision: dict) -> None:
    """Make sure a worked ticket does not stay at 'open'.

    The Boss is asked to set a status but does not always do so, and a ticket
    the team has already reasoned about should never look untouched. This fills
    the gap from the decision itself — never to 'resolved', which only a settled
    payment or an explicit agent call may do.
    """
    current = tool("get_ticket", ticket_id=ticket_id).get("ticket", {}).get("status")
    if current != "open":
        return
    if decision.get("approvals_needed"):
        status, why = "awaiting_approval", "Run finished; payment awaiting human approval."
    elif decision.get("blocked_by"):
        status, why = "blocked", "Run finished; ticket is blocked."
    else:
        return
    tool(
        "update_ticket_status",
        ticket_id=ticket_id,
        status=status,
        note=why,
        updated_by="backend",
    )


async def _run_and_store(run_key: str, ticket_id: int, instruction: str) -> None:
    """Run the team and keep the result for polling."""
    try:
        result = await run_ticket(ticket_id, instruction)
        _settle_status(ticket_id, result.get("decision", {}))
        RUNS[run_key] = {"status": "finished", "ticket_id": ticket_id, **result}
    except Exception as exc:
        RUNS[run_key] = {
            "status": "failed",
            "ticket_id": ticket_id,
            "error": f"{type(exc).__name__}: {exc}",
        }


@app.post("/tickets/{ticket_id}/run")
async def run_ticket_route(
    ticket_id: int, body: RunRequest, background: BackgroundTasks
) -> dict:
    """Run the agent team on a ticket.

    Returns immediately with a key to poll — a full run takes minutes, and the
    board should stay responsive and show progress from `/events` meanwhile.
    """
    board = tool("get_ticket", ticket_id=ticket_id)
    if "error" in board:
        raise HTTPException(404, board["error"])

    run_key = f"ticket-{ticket_id}-{len(RUNS) + 1}"
    RUNS[run_key] = {"status": "running", "ticket_id": ticket_id}
    background.add_task(_run_and_store, run_key, ticket_id, body.instruction)
    return {
        "run_key": run_key,
        "ticket_id": ticket_id,
        "status": "running",
        "model": MODEL_NAME,
        "poll": f"/runs/{run_key}",
    }


@app.get("/runs/{run_key}")
def get_run(run_key: str) -> dict:
    """Status and, once finished, the Boss's decision for a run."""
    run = RUNS.get(run_key)
    if run is None:
        raise HTTPException(404, f"No run {run_key!r}.")
    return run


@app.get("/runs")
def list_runs() -> dict:
    """Every run this process has started."""
    return {"count": len(RUNS), "runs": RUNS}


class AskRequest(BaseModel):
    role: Role
    question: str
    ticket_id: int | None = None


@app.post("/ask")
async def ask_agent(body: AskRequest) -> dict:
    """Ask one agent directly — useful for testing a single role from the board."""
    return await ask(body.role, body.question, body.ticket_id)


# ---------------------------------------------------------------- events


@app.get("/events")
def events(limit: int = 50, run_id: str | None = None, since: str | None = None) -> dict:
    """Recent agent activity: what each agent said and which tools it used.

    Read from the append-only audit trail, so it survives a backend restart and
    shows runs started before this process came up.
    """
    steps = audit.read_all()
    if run_id:
        steps = [s for s in steps if s.get("run_id") == run_id]
    if since:
        steps = [s for s in steps if s.get("ts", "") > since]
    recent = steps[-limit:]
    return {
        "count": len(recent),
        "total": len(steps),
        "latest_ts": recent[-1]["ts"] if recent else None,
        "events": recent,
    }


@app.get("/events/runs")
def event_runs() -> dict:
    """Summary of every run in the audit trail."""
    return {"runs": audit.runs()}


# ------------------------------------------------------------- approvals


@app.get("/approvals")
def list_approvals(status: str = "all") -> dict:
    """Payments the agents have prepared, and where each one stands."""
    return tool("list_approvals", status=status)


class DecisionRequest(BaseModel):
    decided_by: str = Field(description="The person approving — recorded on the payment.")


@app.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, body: DecisionRequest) -> dict:
    """A human approves a prepared payment, and the money actually moves.

    This is the only place cash changes. The agents can only ever queue a
    request as pending — `decide_approval` is filtered out of their toolset — so
    this route is the gate, not a formality.

    Two MCP calls, in order: record the human decision, then settle it. If the
    payment is refused (insufficient cash), the approval stays decided but the
    refusal is returned and no money moves.
    """
    if not body.decided_by.strip():
        raise HTTPException(400, "decided_by is required — approvals must name a person.")

    queued = next(
        (a for a in tool("list_approvals")["approvals"] if a["id"] == approval_id), None
    )
    if queued is None:
        raise HTTPException(404, f"No approval {approval_id}.")

    decision = tool(
        "decide_approval",
        approval_id=approval_id,
        decision="approved",
        decided_by=body.decided_by,
    )
    if "error" in decision:
        raise HTTPException(400, decision["error"])

    # A discount or a purchase order is approved, not paid — no cash moves now.
    if queued["kind"] not in PAYMENT_KINDS:
        notes = []
        for tid in _dependent_tickets(queued):
            notes.append(
                tool(
                    "update_ticket_status",
                    ticket_id=tid,
                    status="resolved",
                    note=f"{queued['kind'].title()} '{queued['payee']}' approved by {body.decided_by}.",
                    updated_by=body.decided_by,
                )
            )
        audit.record(
            run_id=f"human-{approval_id}",
            step="human_approval",
            actor=body.decided_by,
            ticket_id=queued.get("ticket_id"),
            target="decide_approval",
            detail={"approval_id": approval_id, "kind": queued["kind"]},
            result=decision,
        )
        return {
            "approved": True,
            "paid": False,
            "kind": queued["kind"],
            "decision": decision,
            "ticket_closed": notes,
            "note": "Approved. No money moved — this was a commitment, not a payment.",
        }

    payment = tool("pay_approved", approval_id=approval_id, paid_by="backend")
    linked = queued
    audit.record(
        run_id=f"human-{approval_id}",
        step="human_approval",
        actor=body.decided_by,
        ticket_id=linked.get("ticket_id") if linked else None,
        target="pay_approved",
        detail={"approval_id": approval_id},
        result=payment,
    )
    if payment.get("refused"):
        return {"approved": True, "paid": False, "decision": decision, "payment": payment}

    # The payment was the thing the ticket was waiting on, so close it. Agents
    # deliberately leave a ticket in 'awaiting_approval'; only a settled payment
    # authorised by a person can move it to resolved.
    closed = []
    if linked:
        for tid in _dependent_tickets(linked):
            closed.append(
                tool(
                    "update_ticket_status",
                    ticket_id=tid,
                    status="resolved",
                    note=(
                        f"Payment of {payment['amount']:.2f} to {payment['payee']} "
                        f"authorised by {body.decided_by}."
                    ),
                    updated_by=body.decided_by,
                )
            )
    return {
        "approved": True,
        "paid": True,
        "decision": decision,
        "payment": payment,
        "ticket_closed": closed,
    }


@app.post("/approvals/{approval_id}/decline")
def decline(approval_id: int, body: DecisionRequest) -> dict:
    """A human declines a prepared payment. No money moves, ever."""
    result = tool(
        "decide_approval",
        approval_id=approval_id,
        decision="declined",
        decided_by=body.decided_by,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    approval = next(
        (a for a in tool("list_approvals")["approvals"] if a["id"] == approval_id), None
    )
    parked = []
    if approval:
        # A rejected payment is a decision, not a non-event: every ticket that
        # was waiting on this bill is blocked by it and must say so.
        for tid in _dependent_tickets(approval):
            parked.append(
                tool(
                    "update_ticket_status",
                    ticket_id=tid,
                    status="blocked",
                    note=(
                        f"Payment of {approval['amount']:.2f} to {approval['payee']} "
                        f"rejected by {body.decided_by}."
                    ),
                    updated_by=body.decided_by,
                )
            )
    audit.record(
        run_id=f"human-{approval_id}",
        step="human_decline",
        actor=body.decided_by,
        ticket_id=approval.get("ticket_id") if approval else None,
        target="decide_approval",
        detail={"approval_id": approval_id},
        result=result,
    )
    return {"approved": False, "paid": False, "decision": result, "ticket_blocked": parked}


# ------------------------------------------------------------------ cash


@app.get("/cash")
def cash(account: str = "checking") -> dict:
    """The current balance, plus what is still owed against it."""
    result = tool("get_cash_balance", account=account)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@app.get("/payments")
def payments() -> dict:
    """Money that has actually left, with who approved each payment."""
    import db  # the MCP server's database helper

    return {"payments": db.query("SELECT * FROM payments ORDER BY id")}


# ----------------------------------------------------------------- reset


@app.post("/reset")
def reset() -> dict:
    """Restore the working database from the pristine master for a fresh run.

    This wipes every approval, payment, purchase order, draft and ticket-status
    change made since the last reset. The audit trail is deliberately NOT
    cleared — it is append-only, and the record of earlier runs is the thing you
    least want a reset to destroy.
    """
    if not MASTER_DB.exists():
        raise HTTPException(500, f"Master database missing at {MASTER_DB}.")

    before = tool("get_cash_balance")
    shutil.copyfile(MASTER_DB, WORKING_DB)
    after = tool("get_cash_balance")
    RUNS.clear()
    audit.record(
        run_id="reset",
        step="database_reset",
        actor="human",
        detail={"from": str(MASTER_DB.name), "to": str(WORKING_DB.name)},
        result={"balance_before": before.get("balance"), "balance_after": after.get("balance")},
    )
    return {
        "reset": True,
        "balance_before": before.get("balance"),
        "balance_after": after.get("balance"),
        "note": "Working copy restored. Audit trail kept — it is append-only.",
    }


@app.get("/health")
def health() -> dict:
    """Is the backend up, and is it pointed at a working database?"""
    return {
        "ok": WORKING_DB.exists(),
        "model": MODEL_NAME,
        "database": str(WORKING_DB),
        "shop_today": tool("get_cash_balance").get("shop_today"),
    }
