"""Campus Customs Multi-Agent Operations — MCP server.

Every agent on the team calls its tools through this server. It reads the
working copy at `data/campus_customs_new.db`; the original
`data/campus_customs.db` is never opened, so a run can always be reset.

Three tools for now, one per open ticket on the board. More get added in later
problems (pricing and margin, purchase orders, the approval-gated pay tool,
customer drafts).

Ground rules these tools follow:
  * "today" is desk.date_today, never the real clock
  * a vendor will not ship while it has an open unpaid invoice
  * nothing is invented — anything not in the database comes back as an error,
    never as a guess or a placeholder

Run from this folder (stdio):  python server.py
Run (HTTP):                    python server.py --http
HTTP URL:                      http://127.0.0.1:8001/mcp
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from fastmcp import FastMCP

import db

mcp = FastMCP("campus-customs-ops")


def _days_between(start: str, end: str) -> int:
    """Whole days from `start` to `end`, both ISO dates."""
    return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days


@mcp.tool
def list_tickets(status: str = "open") -> dict:
    """List tickets on the board. Pass status='all' to include resolved ones.

    This is the agents' entry point: a ticket carries the SKU, size, quantity
    and the lease or invoice it depends on, so every other lookup starts here
    rather than from a guessed value.
    """
    if status == "all":
        rows = db.query("SELECT * FROM tickets ORDER BY id")
    else:
        rows = db.query("SELECT * FROM tickets WHERE status = ? ORDER BY id", (status,))
    return {"shop_today": db.shop_today(), "count": len(rows), "tickets": rows}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """One ticket with every row it links to: stock, pricing, lease, invoice, vendor.

    Use this before acting on a ticket. The sku/size on a ticket is a soft link
    with no foreign key, so the linked stock row is looked up and returned here
    rather than assumed to exist.
    """
    ticket = db.query_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if ticket is None:
        known = [r["id"] for r in db.query("SELECT id FROM tickets ORDER BY id")]
        return {"error": f"No ticket {ticket_id}.", "ticket_ids_on_file": known}

    linked: dict = {}
    if ticket.get("sku"):
        linked["pricing"] = db.query_one(
            "SELECT * FROM pricing WHERE sku = ?", (ticket["sku"],)
        )
        if ticket.get("size"):
            linked["stock"] = db.query_one(
                "SELECT * FROM inventory WHERE sku = ? AND size = ?",
                (ticket["sku"], ticket["size"]),
            )
    if ticket.get("lease_id"):
        linked["lease"] = db.query_one(
            "SELECT * FROM leases WHERE id = ?", (ticket["lease_id"],)
        )
    if ticket.get("invoice_id"):
        invoice = db.query_one(
            "SELECT * FROM invoices WHERE id = ?", (ticket["invoice_id"],)
        )
        if invoice:
            invoice["days_overdue"] = max(
                0, _days_between(invoice["due_date"], db.shop_today())
            )
            invoice["vendor"] = db.query_one(
                "SELECT * FROM vendors WHERE id = ?", (invoice["vendor_id"],)
            )
        linked["invoice"] = invoice
    return {"shop_today": db.shop_today(), "ticket": ticket, "linked": linked}


@mcp.tool
def get_pricing(sku: str, discount_pct: float = 0.0, qty: int = 1) -> dict:
    """Cost, list price and margin for a SKU, optionally under a discount.

    Used to judge the bulk discount on ticket 103: `below_cost` true means the
    shop would sell for less than the item cost, which is a refusal, not a
    judgement call.
    """
    row = db.query_one("SELECT * FROM pricing WHERE sku = ?", (sku,))
    if row is None:
        known = [r["sku"] for r in db.query("SELECT sku FROM pricing ORDER BY sku")]
        return {"error": f"No pricing row for SKU {sku!r}.", "skus_on_file": known}

    cost, lst = float(row["unit_cost"]), float(row["list_price"])
    price = round(lst * (1 - discount_pct / 100), 2)
    return {
        "sku": sku,
        "unit_cost": cost,
        "list_price": lst,
        "discount_pct": discount_pct,
        "unit_price_after_discount": price,
        "margin_per_unit": round(price - cost, 2),
        "margin_pct": round((price - cost) / price * 100, 1) if price else None,
        "qty": qty,
        "total_revenue": round(price * qty, 2),
        "total_margin": round((price - cost) * qty, 2),
        "below_cost": price < cost,
    }


@mcp.tool
def check_stock(sku: str, size: str, qty_needed: int = 1) -> dict:
    """Check on-hand stock for a SKU and size, and the shortfall against what is needed.

    Used by Inventory for the tee order (ticket 101) and the bulk hoodie
    request (ticket 103). Other sizes are listed for context but never counted
    toward the shortfall — a size M order cannot be filled with size L.

    Unknown SKU or size returns an error rather than a zero, so a missing row is
    never mistaken for "out of stock".
    """
    row = db.query_one(
        "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size)
    )
    if row is None:
        sizes = db.query(
            "SELECT size, qty FROM inventory WHERE sku = ? ORDER BY size", (sku,)
        )
        if not sizes:
            return {"error": f"Unknown SKU {sku!r} — not in the inventory table."}
        return {
            "error": f"SKU {sku!r} has no size {size!r} in the inventory table.",
            "sku": sku,
            "sizes_on_file": sizes,
        }

    on_hand = int(row["qty"])
    shortfall = max(0, qty_needed - on_hand)
    return {
        "sku": sku,
        "name": row["name"],
        "size": size,
        "location": row["location"],
        "qty_needed": qty_needed,
        "on_hand": on_hand,
        "can_fill": shortfall == 0,
        "shortfall": shortfall,
        "other_sizes": db.query(
            "SELECT size, qty FROM inventory WHERE sku = ? AND size != ? ORDER BY size",
            (sku, size),
        ),
    }


@mcp.tool
def check_vendor_availability(sku: str = "") -> dict:
    """List vendors, their lead times, and whether each will ship right now.

    A vendor refuses to ship while it has an open unpaid invoice, so
    `will_ship` is false whenever one is outstanding. This is what blocks the
    tee reprint on ticket 101 — the apparel vendor is owed on an overdue
    invoice, and the lead-day clock only starts once that is paid.

    The database has no SKU-to-vendor column, so this tool does not guess one.
    Pass a `sku` and it reports which vendors are factually linked to it by an
    invoice naming that SKU; the specialty and lead days are returned for every
    vendor so the agent can make the call from real values.
    """
    today = db.shop_today()

    item = None
    if sku:
        item = db.query_one(
            "SELECT DISTINCT sku, name FROM inventory WHERE sku = ?", (sku,)
        )
        if item is None:
            return {"error": f"Unknown SKU {sku!r} — not in the inventory table."}

    vendors = []
    for v in db.query("SELECT * FROM vendors ORDER BY id"):
        open_invoices = db.query(
            "SELECT id, amount, due_date, status, description FROM invoices"
            " WHERE vendor_id = ? AND status != 'paid' ORDER BY id",
            (v["id"],),
        )
        for inv in open_invoices:
            inv["days_overdue"] = max(0, _days_between(inv["due_date"], today))

        blocked = len(open_invoices) > 0
        lead = int(v["lead_days"])
        entry = {
            "vendor_id": v["id"],
            "vendor_name": v["name"],
            "specialty": v["specialty"],
            "lead_days": lead,
            "will_ship": not blocked,
            "blocked_by_unpaid_invoices": open_invoices,
            "amount_owed": round(sum(i["amount"] for i in open_invoices), 2),
            "expected_date_if_ordered_today": (
                None if blocked
                else (date.fromisoformat(today) + timedelta(days=lead)).isoformat()
            ),
        }
        if sku:
            # Only real evidence: invoices from this vendor that name the SKU.
            entry["invoices_naming_sku"] = db.query(
                "SELECT id, amount, due_date, status, description FROM invoices"
                " WHERE vendor_id = ? AND description LIKE ? ORDER BY id",
                (v["id"], f"%{sku}%"),
            )
        vendors.append(entry)

    result = {"shop_today": today, "vendors": vendors}
    if sku:
        result["sku"] = sku
        result["item_name"] = item["name"]
        result["vendors_linked_to_sku_by_invoice"] = [
            v["vendor_name"] for v in vendors if v["invoices_naming_sku"]
        ]
    return result


@mcp.tool
def get_cash_balance(account: str = "checking") -> dict:
    """Current cash in an account, and what it can still cover.

    Money only leaves this shop — no revenue is modelled — so this balance is a
    hard ceiling on everything the team proposes. Accounting should check it
    before preparing any payment.
    """
    row = db.query_one("SELECT * FROM cash_accounts WHERE name = ?", (account,))
    if row is None:
        known = [r["name"] for r in db.query("SELECT name FROM cash_accounts")]
        return {"error": f"No account {account!r}.", "accounts_on_file": known}

    balance = float(row["balance"])
    today = db.shop_today()
    open_invoices = db.query("SELECT id, amount FROM invoices WHERE status != 'paid'")
    # A lease whose rent has already been paid is no longer an obligation —
    # without this the balance double-counts rent after it is settled and the
    # shop looks insolvent when it is not.
    rent_due = db.query(
        "SELECT id, monthly_rent FROM leases WHERE next_due >= ?"
        " AND id NOT IN (SELECT ref_id FROM payments WHERE kind = 'rent'"
        " AND ref_id IS NOT NULL)",
        (today,),
    )
    owed = sum(float(i["amount"]) for i in open_invoices) + sum(
        float(l["monthly_rent"]) for l in rent_due
    )
    return {
        "account": account,
        "balance": balance,
        "as_of": row["date"],
        "shop_today": today,
        "open_invoice_total": round(sum(float(i["amount"]) for i in open_invoices), 2),
        "upcoming_rent_total": round(sum(float(l["monthly_rent"]) for l in rent_due), 2),
        "total_known_obligations": round(owed, 2),
        "balance_after_all_obligations": round(balance - owed, 2),
        "covers_all_obligations": balance >= owed,
    }


@mcp.tool
def list_invoices(status: str = "all") -> dict:
    """Invoices with their vendor and how many days overdue they are.

    Overdue is measured against desk.date_today, not the real calendar. An
    invoice left open is also what stops its vendor shipping.
    """
    today = db.shop_today()
    sql = (
        "SELECT i.*, v.name AS vendor_name, v.lead_days FROM invoices i"
        " JOIN vendors v ON v.id = i.vendor_id"
    )
    rows = (
        db.query(sql + " ORDER BY i.id")
        if status == "all"
        else db.query(sql + " WHERE i.status = ? ORDER BY i.id", (status,))
    )
    for r in rows:
        overdue = _days_between(r["due_date"], today)
        r["days_overdue"] = max(0, overdue)
        r["is_overdue"] = overdue > 0 and r["status"] != "paid"
    return {"shop_today": today, "count": len(rows), "invoices": rows}


@mcp.tool
def get_rent_status(lease_id: int = 1) -> dict:
    """Rent amount and due date for a leased space, plus whether cash covers it.

    Used by Facilities for the rent notice (ticket 102). Days until due are
    measured against desk.date_today, so "due in 2 days" reflects the shop
    clock. The cash figure is reported only so the shortfall is visible — this
    tool never moves money; paying requires the approval-gated pay tool.
    """
    lease = db.query_one("SELECT * FROM leases WHERE id = ?", (lease_id,))
    if lease is None:
        return {"error": f"No lease {lease_id} in the leases table."}

    today = db.shop_today()
    days = _days_between(today, lease["next_due"])
    cash = db.query_one("SELECT * FROM cash_accounts WHERE name = 'checking'")
    rent = float(lease["monthly_rent"])
    balance = float(cash["balance"]) if cash else None

    return {
        "lease_id": lease["id"],
        "space_name": lease["space_name"],
        "landlord": lease["landlord"],
        "monthly_rent": rent,
        "next_due": lease["next_due"],
        "shop_today": today,
        "days_until_due": days,
        "is_overdue": days < 0,
        "checking_balance": balance,
        "cash_covers_rent": None if balance is None else balance >= rent,
        "balance_after_if_paid": None if balance is None else round(balance - rent, 2),
    }


# ------------------------------------------------------------- writes
#
# The approval gate lives here, in the tools, not in the agent prompts. An
# agent can be argued out of an instruction; a tool that refuses cannot.


@mcp.tool
def request_payment_approval(
    kind: str,
    payee: str,
    amount: float,
    reason: str,
    requested_by: str,
    ticket_id: int | None = None,
    ref_id: int | None = None,
    account: str = "checking",
) -> dict:
    """Queue a payment for a human to approve. This does NOT move any money.

    Agents use this to prepare a payment. It always lands in 'pending' — there
    is no argument that lets an agent set it to approved. A human decides on the
    board, and only then can `pay_approved` be called.

    The affordability check runs now as well, so a payment that cannot be
    covered is reported before it ever reaches the human.
    """
    db.init_db()
    cash = db.query_one("SELECT * FROM cash_accounts WHERE name = ?", (account,))
    if cash is None:
        return {"error": f"No account {account!r}."}
    if amount <= 0:
        return {"error": "Amount must be greater than zero."}

    balance = float(cash["balance"])
    if amount > balance:
        return {
            "error": "Insufficient cash — not queued.",
            "amount": amount,
            "balance": balance,
            "short_by": round(amount - balance, 2),
            "note": "The shop has no revenue, so this cannot be covered later.",
        }

    # Idempotent: two agents working the same ticket often both prepare the same
    # payment. Returning the existing pending request keeps one bill from showing
    # up as two cards a human could approve twice.
    # One obligation, one approval — deliberately NOT scoped per ticket. Invoice
    # 501 blocks both the tee order and the hoodie restock, and a second pending
    # row for the same bill is a double payment waiting for an unlucky human.
    # The decision is propagated to every dependent ticket when it is made.
    existing = db.query_one(
        "SELECT * FROM approvals WHERE status = 'pending' AND kind = ? AND amount = ?"
        " AND account = ? AND (ref_id IS ? OR ref_id = ?) LIMIT 1",
        (kind, amount, account, ref_id, ref_id),
    )
    if existing:
        return {
            "approval_id": existing["id"],
            "status": "pending",
            "kind": kind,
            "payee": existing["payee"],
            "amount": amount,
            "account": account,
            "balance_now": balance,
            "balance_if_approved": round(balance - amount, 2),
            "already_queued": True,
            "note": (
                f"This bill is already pending as approval {existing['id']}, "
                f"prepared by {existing['requested_by']} for ticket "
                f"{existing['ticket_id']}. Reusing it rather than queuing a "
                "duplicate — it only needs paying once."
            ),
        }

    approval_id = db.execute(
        "INSERT INTO approvals (ticket_id, kind, ref_id, payee, amount, account,"
        " reason, requested_by, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (ticket_id, kind, ref_id, payee, amount, account, reason, requested_by,
         db.shop_today()),
    )
    return {
        "approval_id": approval_id,
        "status": "pending",
        "kind": kind,
        "payee": payee,
        "amount": amount,
        "account": account,
        "balance_now": balance,
        "balance_if_approved": round(balance - amount, 2),
        "note": "Pending human approval. No money has moved.",
    }


@mcp.tool
def request_decision_approval(
    kind: str,
    subject: str,
    detail: str,
    requested_by: str,
    ticket_id: int | None = None,
    value: float = 0.0,
    ref_id: int | None = None,
) -> dict:
    """Queue a non-payment decision for a human: a discount, or a purchase order.

    Not every decision that needs a person moves money. Granting a bulk discount
    costs margin rather than cash, and raising a purchase order commits the shop
    to a spend later. Both belong to a human, and neither fits
    `request_payment_approval`, which exists to move money out of an account.

    `kind` must be 'discount' or 'purchase'. `value` is what is at stake — the
    margin given away, or the cost of the order — so the human can see the size
    of what they are agreeing to. Nothing is applied until it is approved.
    """
    db.init_db()
    allowed = {"discount", "purchase"}
    if kind not in allowed:
        return {
            "error": f"kind must be one of {sorted(allowed)}.",
            "got": kind,
            "note": "Use request_payment_approval to move money out of an account.",
        }

    existing = db.query_one(
        "SELECT * FROM approvals WHERE status = 'pending' AND kind = ?"
        " AND (ticket_id IS ? OR ticket_id = ?) LIMIT 1",
        (kind, ticket_id, ticket_id),
    )
    if existing:
        return {
            "approval_id": existing["id"],
            "status": "pending",
            "kind": kind,
            "already_queued": True,
            "note": (
                f"A {kind} decision for this ticket is already pending as "
                f"approval {existing['id']}."
            ),
        }

    approval_id = db.execute(
        "INSERT INTO approvals (ticket_id, kind, ref_id, payee, amount, account,"
        " reason, requested_by, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'n/a', ?, ?, 'pending', ?)",
        (ticket_id, kind, ref_id, subject, value, detail, requested_by,
         db.shop_today()),
    )
    return {
        "approval_id": approval_id,
        "status": "pending",
        "kind": kind,
        "subject": subject,
        "value_at_stake": value,
        "note": "Pending human approval. Nothing has been applied or ordered.",
    }


@mcp.tool
def list_approvals(status: str = "all") -> dict:
    """Payment requests and where each one stands. Read-only."""
    db.init_db()
    rows = (
        db.query("SELECT * FROM approvals ORDER BY id")
        if status == "all"
        else db.query("SELECT * FROM approvals WHERE status = ? ORDER BY id", (status,))
    )
    return {"count": len(rows), "approvals": rows}


@mcp.tool
def pay_approved(approval_id: int, paid_by: str) -> dict:
    """Pay a request a human has already approved. Refuses in every other case.

    This is the only tool that moves money, and it enforces both hard rules:

    * **Approval** — the request must already be 'approved'. A pending or
      declined request is refused. No agent can approve one, so an agent cannot
      reach this successfully on its own.
    * **No negative balance** — if the amount exceeds the balance the payment is
      refused outright. Cash never goes below zero, and since no revenue is
      modelled it could never be recovered.

    On success the payment row and the new balance are written in one
    transaction, so the books cannot half-move.
    """
    db.init_db()
    approval = db.query_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if approval is None:
        return {"error": f"No approval {approval_id}."}

    if approval["status"] != "approved":
        return {
            "refused": True,
            "reason": f"Approval {approval_id} is {approval['status']}, not approved.",
            "rule": "A human must approve a payment before it can be made.",
            "status": approval["status"],
        }
    if approval["payment_id"]:
        return {
            "refused": True,
            "reason": f"Approval {approval_id} was already paid.",
            "payment_id": approval["payment_id"],
        }

    # Defence in depth: even if two approvals for one bill ever reach this
    # point, the obligation itself may only be settled once.
    if approval["ref_id"] is not None:
        already = db.query_one(
            "SELECT * FROM payments WHERE kind = ? AND ref_id = ?",
            (approval["kind"], approval["ref_id"]),
        )
        if already:
            return {
                "refused": True,
                "reason": (
                    f"{approval['kind']} {approval['ref_id']} was already settled "
                    f"by payment {already['id']}."
                ),
                "rule": "An obligation may only be paid once.",
                "payment_id": already["id"],
            }

    account = approval["account"]
    amount = float(approval["amount"])
    cash = db.query_one("SELECT * FROM cash_accounts WHERE name = ?", (account,))
    if cash is None:
        return {"error": f"No account {account!r}."}

    balance = float(cash["balance"])
    if amount > balance:
        return {
            "refused": True,
            "reason": "Insufficient cash.",
            "rule": "The balance may never go negative.",
            "amount": amount,
            "balance": balance,
            "short_by": round(amount - balance, 2),
        }

    today = db.shop_today()
    new_balance = round(balance - amount, 2)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (approval["kind"], approval["ref_id"], amount, account, today,
             approval["decided_by"] or "human"),
        )
        payment_id = cur.lastrowid
        conn.execute(
            "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
            (new_balance, today, account),
        )
        if approval["kind"] == "invoice" and approval["ref_id"]:
            conn.execute(
                "UPDATE invoices SET status = 'paid' WHERE id = ?",
                (approval["ref_id"],),
            )
        conn.execute(
            "UPDATE approvals SET payment_id = ? WHERE id = ?",
            (payment_id, approval_id),
        )
        conn.commit()

    return {
        "paid": True,
        "payment_id": payment_id,
        "approval_id": approval_id,
        "kind": approval["kind"],
        "payee": approval["payee"],
        "amount": amount,
        "account": account,
        "approved_by": approval["decided_by"] or "human",
        "paid_by": paid_by,
        "balance_before": balance,
        "balance_after": new_balance,
        "invoice_marked_paid": approval["ref_id"] if approval["kind"] == "invoice" else None,
    }


@mcp.tool
def create_purchase_order(
    vendor_id: int,
    sku: str,
    size: str,
    qty: int,
    created_by: str,
    ticket_id: int | None = None,
) -> dict:
    """Raise a restock order with a vendor. Refuses if that vendor is blocked.

    A vendor will not ship while it has an open unpaid invoice, so this tool
    checks that first rather than writing an order that could never be filled.
    The expected date is the shop's today plus the vendor's lead days — both
    from the database, never estimated.
    """
    db.init_db()
    vendor = db.query_one("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
    if vendor is None:
        return {"error": f"No vendor {vendor_id}."}
    if qty <= 0:
        return {"error": "Quantity must be greater than zero."}

    stock = db.query_one(
        "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size)
    )
    if stock is None:
        return {"error": f"No inventory row for {sku!r} size {size!r}."}

    open_invoices = db.query(
        "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status != 'paid'",
        (vendor_id,),
    )
    if open_invoices:
        return {
            "refused": True,
            "reason": f"{vendor['name']} has an unpaid invoice and will not ship.",
            "rule": "A vendor will not ship new product while an invoice is open.",
            "open_invoices": open_invoices,
            "fix": "Settle the invoice first — that needs human approval.",
        }

    price = db.query_one("SELECT * FROM pricing WHERE sku = ?", (sku,))
    if price is None:
        return {"error": f"No pricing row for SKU {sku!r} — cannot cost the order."}

    today = db.shop_today()
    expected = (
        date.fromisoformat(today) + timedelta(days=int(vendor["lead_days"]))
    ).isoformat()
    unit_cost = float(price["unit_cost"])
    total = round(unit_cost * qty, 2)
    po_id = db.execute(
        "INSERT INTO purchase_orders (ticket_id, vendor_id, sku, size, qty,"
        " unit_cost, total_cost, expected_date, status, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        (ticket_id, vendor_id, sku, size, qty, unit_cost, total, expected,
         created_by, today),
    )
    return {
        "purchase_order_id": po_id,
        "vendor": vendor["name"],
        "sku": sku,
        "size": size,
        "qty": qty,
        "unit_cost": unit_cost,
        "total_cost": total,
        "lead_days": vendor["lead_days"],
        "expected_date": expected,
        "status": "open",
        "note": "Order recorded on the board. No vendor has been contacted.",
    }


@mcp.tool
def save_customer_draft(
    ticket_id: int,
    audience: str,
    subject: str,
    body: str,
    author: str,
    check_before_sending: str = "",
) -> dict:
    """Save a customer message to the board as a draft. Nothing is ever sent.

    There is deliberately no tool that sends a message anywhere. Drafts sit on
    the board for a human to read, edit and send themselves.
    """
    db.init_db()
    # One reply per ticket per audience. An agent re-saving the same message
    # should update it, not stack identical cards on the board for a human to
    # read three times.
    existing = db.query_one(
        "SELECT * FROM drafts WHERE ticket_id IS ? AND audience = ? AND status = 'draft'"
        " ORDER BY id LIMIT 1",
        (ticket_id, audience),
    )
    if existing:
        db.execute(
            "UPDATE drafts SET subject = ?, body = ?, check_before_sending = ?,"
            " author = ? WHERE id = ?",
            (subject, body, check_before_sending, author, existing["id"]),
        )
        return {
            "draft_id": existing["id"],
            "ticket_id": ticket_id,
            "audience": audience,
            "subject": subject,
            "status": "draft",
            "updated_existing": True,
            "note": (
                f"Draft {existing['id']} for this ticket is saved and updated. "
                "This is done — do not call this tool again for this ticket. "
                "Not sent; no tool can send it."
            ),
        }

    draft_id = db.execute(
        "INSERT INTO drafts (ticket_id, audience, subject, body,"
        " check_before_sending, author, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
        (ticket_id, audience, subject, body, check_before_sending, author,
         db.shop_today()),
    )
    return {
        "draft_id": draft_id,
        "ticket_id": ticket_id,
        "audience": audience,
        "subject": subject,
        "status": "draft",
        "note": (
            "Saved to the board. This is done — do not call this tool again for "
            "this ticket. Not sent; no tool can send it."
        ),
    }


@mcp.tool
def update_ticket_status(ticket_id: int, status: str, note: str, updated_by: str) -> dict:
    """Move a ticket to a new status and append a note explaining why.

    Allowed: 'open', 'blocked', 'awaiting_approval', 'resolved'. A ticket that
    depends on an undecided payment belongs in 'awaiting_approval', not
    'resolved' — the work is not finished until the human has acted.
    """
    allowed = {"open", "blocked", "awaiting_approval", "resolved"}
    if status not in allowed:
        return {"error": f"Status must be one of {sorted(allowed)}.", "got": status}

    ticket = db.query_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if ticket is None:
        return {"error": f"No ticket {ticket_id}."}

    stamped = f"[{db.shop_today()} {updated_by}] {note}"
    notes = f"{ticket['notes']}\n{stamped}" if ticket["notes"] else stamped
    db.execute(
        "UPDATE tickets SET status = ?, notes = ? WHERE id = ?",
        (status, notes, ticket_id),
    )
    return {
        "ticket_id": ticket_id,
        "status_before": ticket["status"],
        "status": status,
        "note_added": stamped,
    }


@mcp.tool
def decide_approval(approval_id: int, decision: str, decided_by: str) -> dict:
    """**Human only.** Approve or decline a queued payment.

    This tool is not given to the agents — the backend calls it when a person
    clicks approve or decline on the dashboard. It is the only way an approval
    leaves 'pending', which is what makes the gate in `pay_approved` real
    rather than a convention the agents are asked to respect.

    `decided_by` is recorded and copied onto the payment row as the audit trail
    showing who authorised the money leaving.
    """
    db.init_db()
    if decision not in {"approved", "declined"}:
        return {"error": "Decision must be 'approved' or 'declined'.", "got": decision}
    if not decided_by.strip():
        return {"error": "decided_by is required — approvals must name a person."}

    approval = db.query_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if approval is None:
        return {"error": f"No approval {approval_id}."}
    if approval["status"] != "pending":
        return {
            "error": f"Approval {approval_id} is already {approval['status']}.",
            "decided_by": approval["decided_by"],
        }

    db.execute(
        "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
        (decision, decided_by, db.shop_today(), approval_id),
    )
    return {
        "approval_id": approval_id,
        "status": decision,
        "decided_by": decided_by,
        "decided_at": db.shop_today(),
        "next": "Call pay_approved to settle it." if decision == "approved" else "No payment will be made.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Campus Customs operations MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve Streamable HTTP on port 8001 (keeps FastAPI free on 8000)",
    )
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="http", host="127.0.0.1", port=8001)
    else:
        mcp.run()
