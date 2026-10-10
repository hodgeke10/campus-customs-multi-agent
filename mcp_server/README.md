# Campus Customs Operations — MCP Server

The tool layer for Campus Customs Multi-Agent Operations. Every agent on the
team — Boss, Inventory, Accounting, Facilities, Customer Service — reaches the
shop's data through this server rather than touching SQL directly, so the shop's
rules are enforced in one place instead of in five prompts. There is no second
shop-tools layer: the backend and the agents call this same server.

Server name: `campus-customs-ops` (FastMCP) — **16 tools**

## Database

Reads and writes **`data/campus_customs_new.db`**, the working copy that gets
updated as tickets are resolved.

The original **`data/campus_customs.db`** is never opened by this server. That
keeps it clean as a reset point — to start the tickets over:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

The path is defined once in `db.py` (`DB_PATH`), so no tool can reach the
master by accident.

Three tables are not in the original shop database and are created on demand in
the working copy: `approvals`, `purchase_orders`, `drafts`.

## Read tools (8)

### `list_tickets(status="open")`
The board. Pass `status="all"` for resolved tickets too.

### `get_ticket(ticket_id)`
One ticket plus every row it links to — stock, pricing, lease, invoice and the
invoice's vendor, with overdue days computed. Call this before acting on a
ticket; it is how an agent learns the real SKU, size and quantity.

### `check_stock(sku, size, qty_needed=1)`
On-hand quantity and the shortfall. Other sizes are returned for context but
never count toward the fill — a size M order cannot be filled with size L.

### `check_vendor_availability(sku="")`
Every vendor with specialty, lead days, and `will_ship`, which is false while
the vendor has an open unpaid invoice. The expected date is returned only when
the vendor can actually ship.

### `get_pricing(sku, discount_pct=0.0, qty=1)`
Unit cost, list price, margin per unit and total under a discount, plus a
`below_cost` flag.

### `get_cash_balance(account="checking")`
The balance, total known obligations, and what would remain after all of them.
Money only leaves this shop, so this is a hard ceiling.

### `list_invoices(status="all")`
Invoices with vendor and days overdue, measured against the shop clock.

### `get_rent_status(lease_id=1)`
Rent amount, due date, days until due on the shop clock, and whether cash
covers it. Reports only; never moves money.

## Write tools (7)

### `request_payment_approval(kind, payee, amount, reason, requested_by, ...)`
Queues a payment for a human. Always lands in `pending` — no argument sets it
approved. Refuses up front if the amount exceeds the balance.

### `request_decision_approval(kind, subject, detail, requested_by, ticket_id, value)`
Queues a non-payment decision for a human: a `discount` or a `purchase`. `value`
is what is at stake — margin given away, or the cost of the order. Nothing is
applied until approved, and no cash moves when it is.

### `list_approvals(status="all")`
What is pending, approved or declined. Read-only.

### `pay_approved(approval_id, paid_by)`
**The only tool that moves money.** Refuses unless the approval is `approved`,
refuses anything that would make the balance negative, and refuses a second
payment on the same approval. On success it writes `payments`, decrements
`cash_accounts` and marks the invoice paid in **one transaction**.

### `create_purchase_order(vendor_id, sku, size, qty, created_by, ticket_id=None)`
Raises a restock order. Refuses when the vendor has an open unpaid invoice.
Expected date is shop today plus `vendors.lead_days` — never estimated.

### `save_customer_draft(ticket_id, audience, subject, body, author, ...)`
Saves a message to the board. **Nothing is ever sent** — there is deliberately
no send tool anywhere in this server.

### `update_ticket_status(ticket_id, status, note, updated_by)`
Moves a ticket between `open`, `blocked`, `awaiting_approval` and `resolved`,
appending a stamped note. A ticket waiting on an undecided payment belongs in
`awaiting_approval`, not `resolved`.

## Human-only tool (1)

### `decide_approval(approval_id, decision, decided_by)`
Approve or decline a queued payment. The backend calls this when a person acts
on the dashboard. It is **filtered out of the agents' toolset** in
`backend/config.py` (`HUMAN_ONLY_TOOLS`), so agents see 15 of the 16 tools and
have no path to approve their own payments. This is what makes the gate in
`pay_approved` structural rather than a convention.

## Ground rules the tools enforce

- **"Today" is `desk.date_today`**, never the real clock.
- **A vendor will not ship while it has an open unpaid invoice**, so a restock
  can be blocked by an accounting problem.
- **Human approval for every payment**, and **no negative balances** — both
  enforced by refusal in the tool, not by instructions in a prompt.
- **Nothing is invented.** The database has no SKU-to-vendor column, so
  `check_vendor_availability` does not guess one. An unknown SKU or size returns
  an error, never a `0`.
- **Nothing leaves the shop.** Drafts stay on the board.

## Running it

```bash
python server.py          # stdio
python server.py --http   # http://127.0.0.1:8001/mcp
```

Port 8001 keeps 8000 free for the FastAPI backend. Registered for the vibe coder
in `.mcp.json`.

## Files

| File | Role |
|---|---|
| `server.py` | the FastMCP server and its 16 tools |
| `db.py` | connection helpers, `DB_PATH`, `shop_today()`, agent-table schema |
