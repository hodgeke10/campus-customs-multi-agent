# Dashboard Design — Campus Customs Operations Desk

What the board looks like and why.

---

## The brief

A human sits between five agents and the shop's money. They need four answers
fast:

1. What is on the board, and in what state?
2. What are the agents doing now?
3. Is anything waiting on **me**?
4. How much cash is left?

Everything below serves those four.

---

## Two versions, and why the first lost

**First: a modern product page.** Warm paper, a serif face for the shop name and
dollar figures, soft-shadowed cards, pill badges, an animating balance.

It looked good, but I felt like it looked too modern and AI-generated.

- **Cards fight dense data.** Three tickets, five agents and a queue of
  approvals are *rows*, not objects deserving framed panels. Card padding pushed
  useful facts below the fold.
- **Uniform weight means no hierarchy.** A $2,400 payment awaiting authorisation
  looked exactly like a ticket nobody had touched.
- **It read as decorative** — something to look past rather than through.

**Second, and the one I kept: a late-90s business ticketing terminal.** Dense
grids, square corners, beveled chrome, status codes, a console log. That idiom
already solved this problem, so borrowing it means the layout carries meaning
rather than taste.

---

## Layout: the screen follows the work

```
┌─ title bar ──── date · user · agent state ─┐
├─ toolbar ─────────── CHECKING  3,400.00 ───┤
├─ TICKET QUEUE (full width) ────────────────┤
├─ AGENT STATUS       │ PENDING AUTHORISATION┤
├─ CASE DETAIL ───────┬─ AGENT FINDINGS ─────┤
├─ ACTIVITY LOG (full width) ────────────────┤
└─ status bar ─ MCP · MODEL · DB ····· READY ┘
```

1. **Queue on top** — pick the work first.
2. **Agents and approvals side by side.** Approvals are the only part a human
   can act on, so they sit in peripheral vision while you read agent state.
3. **Case detail split: record left, findings right.** You see what was asked
   and what was concluded without scrolling between them.
4. **Log along the bottom, full width** — chronological and least urgent, but
   its lines are long and wrapping a log destroys scannability.

Agent output is *commentary on*
a request; one column implied the agents had edited the ticket.

---

## How the agents read

Five agents producing prose would be unreadable, so their state is columnar and
terse:

| AGENT | STATE | OPS |
|---|---|---|
| BOSS | DECIDED | 5 |
| INVENTORY | REPORTED | 3 |
| ACCOUNTING | QUEUE PAYMENT | 7 |
| FACILITIES | IDLE | – |

- **`STATE` is a verb phrase**, not a sentence — `STOCK CHECK`, `QUEUE PAYMENT`,
  `-> ACCOUNTING`. Each maps to one tool call or delegation, so the column is a
  live translation of the audit trail into shop language.
- **`OPS` is a tool-call count** — one number for how hard an agent is working,
  and the fastest way to spot a loop. When Accounting was thrashing, OPS read 31
  against everyone else's 3. I saw it immediately.
- **Idle agents are greyed, not hidden.** On the rent ticket, Inventory and
  Customer Service stay dim: *correctly uninvolved* differs from *missing*, and
  dimming makes good routing legible.
- **The working agent is highlighted** green with a blinking square.

### The log speaks shop, not API

It says `STOCK CHECK`, not `check_stock`. Tool names belong in the audit trail;
on screen a human wants the shop's language.

Colour does the triage: cyan timestamps, grey routine ops, **amber delegations**
(one agent handing to another is the interesting event), **green completion**,
**red failure**. You can find where a run went wrong without reading a word.

---

## How tickets show their state

| Code | Meaning | Colour |
|---|---|---|
| `OPEN` | untouched, or running | navy |
| `HOLD-APPR` | waiting on a human | amber |
| `BLOCKED` | stopped — missing stock, rejected payment | red |
| `CLOSED` | finished, money settled | green |

Codes over sentences: a status column should be scannable and the same width on
every row.

**Amber `HOLD-APPR` is the most important state here** — the system saying *I
have done all I can; the rest is yours*. Agents can never write `CLOSED`; only a
settled payment or an approved decision does, through the backend. So a row's
colour is a truthful claim about who holds the baton.

When a run finishes a **✓** appears beside the status. A finished run and a
resolved ticket are different facts, and conflating them would hide this shop's
most important case: the team did its job perfectly *and* the ticket still
cannot close, because a human has not decided.

---

## How cash shows up

A green-on-black LCD readout in the toolbar, Courier, right-aligned, tabular.

- **One number, always in the same place.** Cash only ever leaves this shop, so
  the balance is the one irreversible quantity on screen.
- **It blinks when it changes** — four inverse flashes. Money leaving should be
  impossible to miss even if you were watching the log.
- **`OWED 3,240.00` sits beside it.** $3,400 looks comfortable; $3,400 against
  $3,240 of obligations is the real situation, and that is what should make
  someone pause before approving.
- **The LCD treatment is literal on purpose** — a till, a calculator: the visual
  grammar of money that is counted, not modelled.

---

## The choices that make it a place

- **Beveled chrome.** Buttons physically depress when clicked; panes sit sunken.
  Costs nothing, makes the interface feel built rather than drawn.
- **Navy selection bar.** The selected ticket inverts to white-on-navy. Zero
  ambiguity, and faintly delightful to anyone who has used such a system.
- **A segmented status bar** — `MCP: CAMPUS-CUSTOMS-OPS | MODEL: GPT-6-LUNA |
  DB: CAMPUS_CUSTOMS_NEW ... READY`. Functionally provenance; tonally the small
  print that tells you the machine is real.
- **Courier for numbers, Verdana for words.** Amounts line up; prose stays
  readable.
- **`3 RECORD(S) · 3 OPEN · SELECTED TKT 101`** under the queue — a record count
  is something an operations tool always has and a web app never does.
- **Empty states with voice**: `NO ITEMS AWAITING AUTHORISATION`, `AGENT TEAM
  RUNNING...` — plain, never apologetic, never cute.

**Why it is enjoyable, not merely usable.** The pleasure is density that rewards
attention. Nothing hides behind a disclosure triangle. You learn the whole shop
in one screen, then read it faster every time — the OPS column, the amber rows,
the colour of the last log line. Modern dashboards spend their budget on first
impressions; this one spends it on the fortieth use.

The retro idiom also sets honest expectations. It does not look like a product
that will anticipate your needs. It looks like an instrument panel: it shows
what is true and waits for you to decide. With five LLM agents reaching for the
shop's bank balance, that is the right relationship for an interface to propose.

---

## Why this style is readable to everyone

The strongest reason for the old-fashioned layout is not nostalgia — it is that
people of any age can read it without being taught.

- **Everything is explicit.** Every action is a labelled button, every state is
  a word. Nothing hides behind a hover, a long-press, a swipe or an icon you
  have to decode.
- **Tables are near-universal.** Spreadsheets, bank statements, timetables — a
  grid with headers is one of the few interface conventions almost everyone has
  already met.
- **Controls look like controls.** A raised, bordered button that depresses when
  pressed announces itself. Flat modern interfaces often leave people guessing
  what is clickable.
- **High contrast, generous targets, no colour-only meaning.** Status is a word
  *and* a colour, so nothing is lost to a bad screen or colour blindness.

Being precise about the claim: the styling itself is a learned convention, not
an instinct. Beveled chrome is unfamiliar to someone raised entirely on mobile,
much as a hamburger menu is unfamiliar to someone who was not. What genuinely
carries across ages is the *explicitness* — visible state, labelled controls, no
hidden affordances. The retro idiom is the vehicle; explicitness does the work.

It also pairs well with the subject matter. A person approving a payment should
never wonder what a control does or whether something already happened. An
interface that states everything plainly is the right one to put between a human
and five agents spending real money.

---

## Legibility: a correction

My first terminal version was typographically authentic and too small — 11px
Tahoma, 10px headers. Fine on a 1024×768 CRT, punishing now.

Raised to **13px Verdana** for body and rows, 11.5px headers, 13px Courier for
the log, 17px for the balance, with padding and line-height increased to match —
larger type in unchanged rows just reads as cramped. Verdana over Tahoma for its
wider letterforms. The look survives; the squinting does not.

