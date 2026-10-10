# Campus Customs Database — Study Notes

Source: `data/campus_customs.db` (pristine master, never written)
Working copy: `data/campus_customs_new.db` (what the MCP server and backend use)

Shop "today" is `desk.date_today` = **2026-08-31**. All overdue math uses this
field, never the real clock.

## Tables and fields

| Table | Key | Fields |
|---|---|---|
| `desk` | — | `date_today`, `notes` |
| `tickets` | `id` | `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at` |
| `inventory` | (`sku`,`size`) | `name`, `qty`, `location` |
| `pricing` | `sku` | `unit_cost`, `list_price` |
| `vendors` | `id` | `name`, `specialty`, `lead_days` |
| `leases` | `id` | `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes` |
| `cash_accounts` | `name` | `balance`, `date` |
| `invoices` | `id` | `vendor_id` → `vendors.id`, `amount`, `due_date`, `status`, `description` |
| `payments` | `id` | `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by` |

`tickets` is the hub: it reaches `inventory`/`pricing` through `sku`+`size`,
`leases` through `lease_id`, and `invoices` (then `vendors`) through `invoice_id`.
`payments` starts **empty** — it is the write target when a human approves a
payment, with `approved_by` recording who gave that approval.

Declared foreign keys: `invoices.vendor_id` → `vendors.id`;
`tickets.lease_id` → `leases.id`; `tickets.invoice_id` → `invoices.id`.
`sku`/`size` on a ticket is a soft link — no FK constraint.

## Starting state

- Cash: **checking $3,400.00** (as of 2026-08-31) — only ever decreases
- Invoice 501: **$840.00, due 2026-08-28 → 3 days overdue**
- Lease 1: **$2,400.00/mo, next due 2026-09-02** (2 days out)
- `payments`: 0 rows

## The three open tickets and how they link

### Ticket 101 — `customer_order`, Tauhid Zaman, "Bulldog tee"
`sku=CC-TEE-WHITE`, `size=S`, `qty=1`, **`invoice_id=501`**

- `inventory(CC-TEE-WHITE, S)` → **qty 0**, Aisle B. Cannot fill from stock.
- `pricing(CC-TEE-WHITE)` → cost $8.00, list $28.00
- `invoices.501` → $840.00, **overdue**, "Rush reprint CC-TEE-WHITE S",
  `vendor_id=1` → **Bulldog Print Co**, apparel reprint, **5 day lead**

**The chain that matters:** restocking the tee needs Bulldog Print Co, but
Bulldog holds an open unpaid invoice, and a vendor will not ship while unpaid.
So 101 is blocked behind paying 501 — and the 5-day lead only starts after that.
This ticket is deliberately not solvable by Inventory alone.

### Ticket 102 — `rent_notice`, Elm City Properties, "Rent due"
`lease_id=1`

- `leases.1` → Chapel Street shop, landlord Elm City Properties,
  **$2,400.00**, next due **2026-09-02** (not yet late as of 2026-08-31)
- Touches `cash_accounts.checking` and, once approved, `payments`

### Ticket 103 — `price_override`, Yale AI Club, "Bulk hoodie discount"
`sku=CC-HOOD-NAVY`, `size=M`, `qty=20`

- `inventory(CC-HOOD-NAVY, M)` → **qty 8**. Shortfall of **12** against the
  20 requested. Other sizes (S 4, L 14, XL 6) do not satisfy a size-M order.
- `pricing(CC-HOOD-NAVY)` → cost $22.00, list $58.00 → **62.1% margin**,
  $36.00 of headroom per unit before the discount hits cost
- Restock would be apparel → Bulldog Print Co again (5 day lead, unpaid invoice)

Both a stock question and a margin question, so it needs Inventory *and*
Accounting, with the Boss making the final discount call.

## The cash squeeze

Obligations $2,400 rent + $840 invoice = **$3,240** against **$3,400** on hand.
Both fit, leaving **$160** — but nothing comes in, so sequencing is one-way and
there is no recovery from an overdraft. Paying either one alone still leaves
enough for the other; this is tight by design, not a trap. The pay tool must
refuse anything that would drive the balance negative, and every payment needs
explicit human approval recorded in `payments.approved_by`.
