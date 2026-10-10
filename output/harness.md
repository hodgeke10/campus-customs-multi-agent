# Campus Customs Harness

Reference for Campus Customs Multi-Agent Operations: the data, the MCP tool
layer, the five agents, the API, the dashboard, and the rules that keep agents
from doing damage.

| | |
|---|---|
| **Model** | `gpt-6-luna` via Portkey (`PORTKEY_API_KEY` from the workspace-root `.env`) |
| **Working database** | `data/campus_customs_new.db` — everything reads and writes here |
| **Pristine master** | `data/campus_customs.db` — never opened by the code; the reset source |
| **Shop clock** | `desk.date_today` = **2026-08-31**, never the real calendar |
| **MCP server** | `campus-customs-ops` (FastMCP), 16 tools |
| **Backend** | FastAPI, port 8000, 15 routes |
| **Dashboard** | React + Vite + TypeScript, port 5178 |

```bash
# reset to the opening state
cp data/campus_customs.db data/campus_customs_new.db

# backend  (from Homework-5/backend)
uvicorn main:app --reload --port 8000

# board    (from Homework-5/frontend)
npm run dev
```

---

# 1. Database tables

Nine tables come from the shop. Three more are created on demand in the working
copy for what the team produces.

### Shop tables

| Table | Key | Fields | Why it matters |
|---|---|---|---|
| `desk` | — | `date_today`, `notes` | Defines "today". Every overdue judgement anchors here. |
| `tickets` | `id` | `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at` | The work queue and the board. |
| `inventory` | (`sku`,`size`) | `name`, `qty`, `location` | Can we fill this, per size. |
| `pricing` | `sku` | `unit_cost`, `list_price` | Margin headroom for discounts. |
| `vendors` | `id` | `name`, `specialty`, `lead_days` | Who restocks, and how long it takes. |
| `leases` | `id` | `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes` | Rent and due dates. |
| `cash_accounts` | `name` | `balance`, `date` | The spending ceiling. |
| `invoices` | `id` | `vendor_id`, `amount`, `due_date`, `status`, `description` | What the shop owes; an open one blocks its vendor. |
| `payments` | `id` | `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by` | The only record of money leaving. Starts empty. |

### Agent-side tables (created in the working copy only)

| Table | Purpose |
|---|---|
| `approvals` | Everything waiting on a human: payments, discounts, purchases. |
| `purchase_orders` | Restock orders raised against a vendor. |
| `drafts` | Customer messages. Never sent — there is no send tool. |

### Links

- `tickets.invoice_id` → `invoices.id` → `invoices.vendor_id` → `vendors.id`
- `tickets.lease_id` → `leases.id`
- `tickets.sku` + `size` → `inventory` — **soft link, no foreign key**, so the
  tool layer validates it rather than trusting the schema
- `payments.ref_id` → the invoice or lease being settled, read via `kind`

### Opening state

$3,400.00 in checking · invoice 501 open for $840.00, **3 days overdue** ·
rent $2,400.00 due 2026-09-02 (2 days out) · three tickets open · no payments.
Obligations total $3,240.00, leaving **$160.00**. That is the designed-in squeeze.

---

# 2. MCP tools

All 16 live in `mcp_server/server.py` over the working copy. `db.py` holds
`DB_PATH` once, so no tool can reach the master. **There is no second shop-tools
layer** — the backend and the agents call this same server.

**R** = reads, **W** = writes. Nearly every tool reads `desk`, because no tool
may use the real clock.

### Reads (8)

| Tool | Tables (R) | What it answers |
|---|---|---|
| `list_tickets` | `tickets`, `desk` | what is on the board |
| `get_ticket` | `tickets`, `inventory`, `pricing`, `leases`, `invoices`, `vendors`, `desk` | one ticket plus every linked row |
| `check_stock` | `inventory` | on hand, and the shortfall |
| `check_vendor_availability` | `vendors`, `invoices`, `inventory`, `desk` | who ships, lead days, and whether they will |
| `get_pricing` | `pricing` | margin under a discount, and `below_cost` |
| `get_cash_balance` | `cash_accounts`, `invoices`, `leases`, `payments`, `desk` | balance, obligations, what remains |
| `list_invoices` | `invoices`, `vendors`, `desk` | overdue days on the shop clock |
| `get_rent_status` | `leases`, `cash_accounts`, `desk` | rent, due date, coverage |

### Writes (7, agent-callable)

| Tool | W | What it enforces |
|---|---|---|
| `request_payment_approval` | `approvals` | Queues a payment as **pending**; no argument sets it approved. Refuses if the amount exceeds cash. Deduped per obligation. |
| `request_decision_approval` | `approvals` | Same gate for things that are not payments: a **discount** or a **purchase**. `value` is the margin or cost at stake. |
| `list_approvals` | — | read-only view of the queue |
| `pay_approved` | `payments`, `cash_accounts`, `invoices`, `approvals` | **The only tool that moves money.** See the gate below. |
| `create_purchase_order` | `purchase_orders` | Refuses when the vendor has an open unpaid invoice. Expected date = shop today + `lead_days`, never estimated. |
| `save_customer_draft` | `drafts` | Saves to the board. **No send tool exists anywhere.** |
| `update_ticket_status` | `tickets` | `open` / `blocked` / `awaiting_approval` / `resolved`, with a stamped note. |

### Human-only (1)

`decide_approval(approval_id, decision, decided_by)` — approve or decline.
**Filtered out of the agents' toolset** in `backend/config.py`
(`HUMAN_ONLY_TOOLS`), so agents see 15 of 16 tools and have no code path to move
an approval out of `pending`. This is what makes the gate structural rather than
a prompt convention.

---

# 3. The five agents

PydanticAI, all on `gpt-6-luna`, all sharing one MCP toolset so the rules hold
regardless of who calls a tool.

| File | Role |
|---|---|
| `backend/config.py` | model builder, MCP toolset, prompt loader, per-run tool cache |
| `backend/models.py` | `Role`, `ApprovalRequest`, `Draft`, `AgentReply`, `TicketDecision` |
| `backend/team.py` | the agents, the `delegate` tool, the run loop |
| `backend/prompts/*.md` | one prompt per agent, plus `_shared.md` |

| Agent | Owns | Ticket types | Leans on |
|---|---|---|---|
| **Boss** | Reads every ticket, routes, makes the final call | all three | `get_ticket`, `request_decision_approval`, `update_ticket_status` |
| **Inventory** | Can we fill it; shortfalls, vendors, lead times | `customer_order`, `price_override` | `check_stock`, `check_vendor_availability`, `create_purchase_order` |
| **Accounting** | Cash, invoices, margins; prepares payments | the money side of all three | `get_cash_balance`, `list_invoices`, `get_pricing`, `request_payment_approval` |
| **Facilities** | Lease, landlord, rent | `rent_notice` | `get_rent_status` |
| **Customer Service** | Drafts the reply | any ticket with a customer | `save_customer_draft` |

### Full connectivity

Every agent has `delegate(teammate, question)` reaching all four others,
including back to the Boss. Guards: depth cap of 3, no self-delegation, no
delegating to an agent already up the current chain. `TeamDeps` carries the
ticket id, depth, chain, run id, actor and a shared tool cache into sub-runs.

### Prompt shape

Each prompt stands alone rather than leaning on `_shared.md`: role · its tools ·
ticket types it owns · **the shop rules restated in its own terms** · what is out
of scope · a worked example from a real ticket. Rules are role-specific, not
copied — Facilities is told it never prepares a payment; Accounting is told never
to propose one that would push the balance below zero.

### Two model gotchas

- `gpt-6-luna` rejects function tools on `/chat/completions` unless reasoning
  effort is `'none'`. Fixed with
  `OpenAIChatModelSettings(openai_reasoning_effort="none")`. The Responses API is
  not an alternative: structured output **plus** an MCP toolset returns HTTP 500.
- `uvicorn --reload` watches `.py` only. Editing `prompts/*.md` does **not**
  reload, and the team is built once at startup — prompt changes need a restart.

---

# 4. API routes

FastAPI on port 8000. Every shop read and write goes through the MCP server via
one `tool()` helper. CORS allows `localhost`/`127.0.0.1` on 5173–5179.

- `GET /tickets` — the three tickets with status and `is_open`
- `GET /tickets/{id}` — one ticket plus every linked row
- `POST /tickets/{id}/run` — run the team; returns a `run_key` immediately
- `GET /runs/{run_key}` — poll: running / finished / failed, plus the decision
- `GET /runs` — every run this process started
- `POST /ask` — put a question to a single agent
- `GET /events` — recent agent activity from the audit trail
- `GET /events/runs` — one summary line per run
- `GET /approvals` — the queue and where each item stands
- `POST /approvals/{id}/approve` — a human approves; **the only place cash moves**
- `POST /approvals/{id}/decline` — a human declines; no money moves
- `GET /cash` — balance, obligations, what remains
- `GET /payments` — money that left, with who approved it
- `POST /reset` — restore the working copy from the master
- `GET /health` — up, model, database, shop date

Three behaviours worth knowing:

- **The run route returns immediately.** A run takes 20s–minutes; the board polls
  `/events` for progress instead of blocking.
- **Approve branches on kind.** Payments go through `pay_approved` and move cash;
  a discount or purchase is recorded as a commitment and does not.
- **`/reset` does not clear the audit trail.** It wipes approvals, payments,
  purchase orders, drafts and statuses — but the trail is append-only, and the
  record of earlier runs is what a reset should least be able to destroy.

---

# 5. Dashboard

React + Vite + TypeScript on port 5178, calling `http://localhost:8000` directly
(`API_BASE` in `src/api.ts`, overridable with `VITE_API_BASE`).

Styled as a late-90s business ticketing terminal: dense grids, square beveled
chrome, status codes, a console log. Full rationale in `output/design.md`.

Reading top to bottom: **ticket queue** → **agent status** and **pending
authorisation** side by side → **case detail** (record left, agent findings
right) → **activity log** full width.

- **Agent status** is columnar: `STATE` is a verb phrase mapped from the audit
  trail (`STOCK CHECK`, `QUEUE PAYMENT`, `-> ACCOUNTING`), `OPS` is a tool-call
  count. Idle agents are dimmed, not hidden, so good routing is legible.
- **Statuses**: `OPEN` (navy), `HOLD-APPR` (amber), `BLOCKED` (red),
  `CLOSED` (green). A ✓ marks a finished run, which is a different fact from a
  resolved ticket.
- **Cash** is a green-on-black LCD readout that blinks when it changes, with
  obligations beside it.
- **Findings stay hidden until the team has run**, and are scoped to runs since
  the last reset. Agent restatements are filtered out of the record; only human
  authorisations appear under `AUTHORISATION`.

---

# 6. Safety rules

### Money

1. **A human approves every payment, and nothing agent-side can forge it.**
   `decide_approval` is filtered out of the agents' toolset.
2. **Refusal lives in the tool, not the prompt.** `pay_approved` refuses a
   pending or declined approval, an amount above the balance, a second payment on
   the same approval, and any obligation already settled.
3. **No negative balances** — checked when queued and again when paid.
4. **One obligation, one approval.** Deduped across tickets, with the decision
   propagated to every dependent ticket, so one bill cannot be paid twice.
5. **Writes are atomic** — payment row, balance decrement and invoice status in
   one transaction.
6. **`payments.approved_by` records the person.**
7. **The master database is never opened**, so any run can be thrown away.

### Customers

8. **No send capability exists anywhere.** Not disabled — absent.
9. **Internal business stays internal.** Customer Service may not mention
   invoices, cash, margins or vendor disputes.
10. **No unapproved promises** — no price, discount, refund or date unless a tool
    produced it or a human approved it.
11. **No invented facts.** Unknown SKUs return errors, never zeros.

### What a real business would add

Spend ceilings per agent and per day · dual approval above a threshold · an
off-box write-once audit store · idempotency keys on payments · a kill switch
that revokes write tools without a redeploy · anomaly alerts on unusual payees ·
PII handling and a retention policy on drafts.

### Token limits

`UsageLimits(request_limit=60, tool_calls_limit=90)` shared across a whole
delegation chain · delegation depth capped at 3 with loop guards · structured
outputs · read-only tool results cached per run · audit results truncated at
1,200 characters (except decisions, kept whole) · one shared toolset.

The biggest saving was not a limit: giving each prompt an explicit out-of-scope
section, plus telling Accounting that queuing a payment *is* the finished state
of its job, cut a ticket-101 run from **87 tool calls to 13**.

---

# 7. Audit trail

`output/audit_trail.json` — append-only **JSON Lines**, one object per
agent-loop step, flushed and fsynced per step, so runs accumulate and a crash
keeps everything written up to it. Resets never clear it.

Fields: `ts`, `run_id`, `ticket_id`, `step`, `actor`, `target`, `detail`,
`result`.
Steps: `run_started`, `delegation`, `delegation_reply`, `tool_call`,
`run_finished`, `run_failed`, `human_approval`, `human_decline`,
`database_reset`.

Every MCP call is captured through `process_tool_call` on the toolset, so an
agent cannot skip logging. `run_id` and `actor` propagate into delegated
sub-runs, so a `get_cash_balance` call Accounting makes on the Boss's behalf is
attributed to **Accounting**.

**1,150 steps recorded across all development and testing.** The final clean run
appended **59**: 3 `run_started`, 7 `delegation`, 7 `delegation_reply`, 36
`tool_call`, 3 `run_finished`, 3 `human_approval`.

---

# 8. The full run

Database reset first; both files hash-identical at the start.

| Ticket | First call | Delegations | Tool calls | Raised | Final |
|---|---|---|---|---|---|
| 101 | Boss → Inventory | 2 | 7 (+2 cached) | $840 invoice | **resolved** |
| 102 | Boss → Facilities | 2 | 5 (+2 cached) | $2,400 rent | **resolved** |
| 103 | Boss → Inventory | 3 | 11 (+9 cached) | discount, $116 margin | **resolved** |

**Cash: $3,400.00 − $3,240.00 = $160.00**, matching `cash_accounts.balance`.
Two payment rows, both `approved_by = operator`. The discount moved no cash.

Artifacts: `output/resolved_tickets.json`, `output/resolved_board.html`,
`output/desk_tickets.html` (Expected vs Actual), `output/design.md`.

### Plan vs outcome

**Right:** every first call; Facilities absent from 101 and 103; Inventory and
Customer Service absent from 102; 102 the shortest run; no promised delivery
date; sizes not fungible; no invented vendor; no payment tool on 103; no
duplicate approvals.

**Wrong:** the lateral hand-offs I predicted on 101 and 102 both went through the
Boss, while the one lateral hop that did happen was on 103, where I argued it was
unnecessary; **no customer drafts were written on any ticket**; and 103 raised a
discount approval, a kind that did not exist when the plan was written.

---

## Follow-up fix: the customer was never answered

The full run closed all three tickets without writing a single customer draft.
Customer Service was never consulted. Three causes, found by reading
`boss.md` rather than guessing:

1. **The Boss's completion checklist never mentioned a reply.** "Your decision
   must contain" listed five items — facts, blockers, decision, approvals, next
   step. A customer reply was not one of them.
2. **Routing mentioned Customer Service in passing**, as a trailing clause in a
   list of ticket types, with none of the force of the rules it did follow.
3. **An earlier fix of mine made it worse.** To get ticket 103 to queue a
   discount I added a "Before you finish" section whose three completion
   triggers were all approvals — effectively teaching the Boss that queuing an
   approval is what finishing looks like.

**Fixes.** `boss.md` now applies the same finishing test to the requester: a
customer waiting with no draft means the ticket is not finished, stated to apply
even when the news is bad and even when there is no date to give. The reply was
added to "Your decision must contain", routing says **always** Customer Service,
and the worked example ends with the draft. `customer_service.md` now requires
`save_customer_draft` and names it in the tool list.

**Two bugs this surfaced, both fixed in the tool layer:**

- Customer Service saved **three identical drafts**. `save_customer_draft` is now
  idempotent per ticket and audience — it updates the existing draft instead of
  stacking duplicates.
- It then called the tool **39 times**, blowing the request limit and failing the
  run — the same loop Accounting had. Fixed the same way: the prompt says call it
  exactly once and stop, and the tool's own reply now says the job is done.

**Verified:** 101 drafts to Tauhid Zaman, 103 drafts to the Yale AI Club, 102
produces none because a landlord is not a customer. One draft row per ticket,
one `save_customer_draft` call per run, 15 tool calls on 101.
