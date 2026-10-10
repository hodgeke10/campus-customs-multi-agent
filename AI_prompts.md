# AI Prompts Log — Homework 5

What I typed into the vibe coder, quoted as written.
Model: `gpt-6-luna` via Portkey. Session date: 2026-10-10.

---

## Scenario

> today we're in hw5

> Here's the scenario (don't do anything yet this is just for info):
> Campus Customs Multi-Agent Operations is the agentic team that runs the shop. Open tickets land on a board - customer orders, rent, unpaid bills, discount requests, whatever the shop has to handle. You will build three pieces that talk to each other: an MCP server, a FastAPI backend with a multi-agent team, and a React dashboard so a human can watch the agents at work and approve requests.
> Your agent team has full connectivity - any agent may delegate task to any other agent for help. In this assignment we will build these agents:
>
> * Boss - reads each ticket, decides who should work on it, and makes final calls
> * Inventory - checks stock by SKU and size, spots shortfalls, and figures out which vendor can restock
> * Accounting - watches cash and invoices, checks margins, and prepares payments or purchase orders for human approval
> * Facilities - handles the shop space side (leases, rent, etc)
> * Customer Service - drafts messages for customers

> These are the rules of this shop:
>
> * the field desk.date_today is "today" for the shop. use this date to determine was it overdue
> * vendor lead times come from the vendors table
> * a vendor will not ship new product while they still have an open unpaid invoice
> * human approval is required for any payments. points will be deducted if this is not done (so it's important!!) if payment is made, make sure to update the relevant table.
> * if there is not enough cash, the pay tool must refuse - no negative balances
> * cash only goes out in this homework - we did not model revenue, so no money comes in
> * before a full run to resolve the tickets, make sure to reset the database to the original values
> * do not email customers or call real vendors. drafts stay on the board

> for this assignment use only gpt-6-luna

---

## Problem 1 — Vibe coder prompts

> Create AI_prompts.md as a log of what I type into the vibe coder. Use actual quotes to make it clear what I wrote

**Follow-up**

> put one section for each problem. each section must include:
>
> * the problem number and title
> * at least one prompt I typed in my own words
> * one follow up prompt if I needed it and one sentence on what was lacking after the first

*What was lacking:* the first version was one flat list of every message, so it
did not map the prompts onto the problems.

---

## Problem 2 — Study the Campus Customs database

> unzip data.zip so we have data/campus_customs.db . That file is the original shop database. Tables include desk, tickets, inventory, pricing, vendors, leases, cash_accounts, payments, and invoices

> our tools will update the database as tickets get resolves. Make a copy of the database file called data/campus_customs_new.db and point the MCP server and backend at that working copy. Keep campus_customs.db untouched so we can reset when we want to restart resolving the tickets

**Follow-up**

> open data/campus_customs.db and look through every table and its fields. copy the original file to data/campus_customs_new.db - later problems update that working copy. Study the three open tickets so you can see how they link to other tabels

*What was lacking:* the unzip gave me the file but no understanding of it, so I
had to ask for every table to be walked and the three tickets traced to the rows
they depend on. Written up in `DB_NOTES.md`.

> start output/harness.md. for each table, list the fields and one short line on why that table matters for the agents. we will keep growing this harness file in later problems

---

---

## Problem 3 — Build the MCP server

> write an MCP server in mcp_server/ using fastMCP. It will talk to data/campus_customs_new.db. You do not need to connect or run it in this problem.

**Follow-up**

> every agent in this homework uses the tools in this MCP server. we will add more tools to it later, for now write three tools we will need for the tickets in the database. keep the names clear. never invent any data, only use information in the database

*What was lacking:* the first pass built out a wide set of read tools, when what
I wanted was three clearly named ones aimed at the open tickets — and the
"never invent data" rule caught a vendor lookup that was guessing a SKU-to-vendor
mapping the database does not contain.

> in output/harness.md, list each of our three MCP tools. For every tool include: which table it reads, which ticket it helps unlock (101, 102, or 103) and one sentence on why that tool is the right one for that ticket. Vague lines like "reads inventory" score low - tie the tool to the ticket

> also add a short mcp_server/README.md file that explains what the MCP server is for, which database file it uses, and the three tools it has.

---

## Problem 4 — Add the MCP server to vibe coder and test each tool

> add the MCP server to this project in claude so the vibe coder can call the tools. Save the connection JSON text in .mcp.json at the project root (or however you normally save local MCP server lists)

**Follow-up**

> with the vibe coder connected, test each of our three MCP tools. save the evidence in output/mcp_smoke.json. For every tool include: 1) the prompt I asked the vibe coder 2)the tool name 3) the tool output (must match values in data/campus_customs_new.db

*What was lacking:* writing `.mcp.json` registers the server but does not prove it
works, so the tools still had to be called end to end and their output checked
back against the database.

Checked in a fresh session with the server connected:

> Is the MCP server working?

> check the other two tools work too

All three tools answered with live data: `get_rent_status` returned $2,400 due
2026-09-02 against a $3,400 balance, `check_vendor_availability` showed Bulldog
Print Co blocked by the $840 invoice 3 days overdue while the other two vendors
will ship, and `check_stock` returned 0 on hand for `CC-TEE-WHITE` size S with
the other sizes correctly excluded from the shortfall.

---

## Problem 5 — Build the agent team and grow the MCP tools

> build the agentic team for Campus Customs using PydanticAI: Boss, Inventory, Accounting, Facilities, and Customer Service. Include prompts, models, and agent loops so they can delegate work to each other with full connectivity.

**Follow-up**

> put the agent prompts in backend/prompts/ - one file per agent. Put data types in backend/models.py, and the agent files under backend/ (your layout can vary as long as the five roles are clear). Use the PORTKEY_API_KEY and only gpt-6-luna for every agent.

*What was lacking:* the first prompt did not pin down where things live, so the
follow-up fixed the layout — prompts one per file, types in `models.py` — and
restated that every agent runs on `gpt-6-luna` through Portkey.

Running the team then exposed two real gaps in the MCP server: the agents had no
way to read a ticket (Inventory guessed a SKU that does not exist and correctly
refused to proceed), and Accounting had no cash tool. Added `list_tickets`,
`get_ticket`, `get_pricing`, `get_cash_balance` and `list_invoices`, taking the
server from three tools to eight.

> add any tools the agents need to the MCP server so they can work on the open tickets. Shop facts come from the MCP server over data/campus_customs_new.db - do not invent a second shop-tools layer that bypasses MCP.

> wire the agents so they append to output/audit_trail.json as they run: for each agent-loop step, record enough to audit later. Append to this file, do not wipe it each run.

*What was lacking:* the eight read tools let the agents understand a ticket but not
act on one — no way to queue a payment, raise a purchase order, save a draft or
move a ticket's status. Added six write tools plus a human-only `decide_approval`
that is filtered out of the agents' toolset, so no agent can approve its own
payment.

> in output/harness.md list each agent and each MCP tool (including ones we add in this problem) along with which table the tool uses. Also add a short safety section: the guardrails a real business would want when agents touch real customers and real money, plus limits that keep token use in check.

Then, on the prompts themselves:

> for the agent prompts, each prompt should be based on the shop rules. more detailed prompts that cover all aspects of an agent's work and scope score higher. how can I improve the prompts?

*What was lacking:* the shop rules lived almost entirely in a shared file, so each
role prompt was thin on them — `boss.md` never mentioned the shop clock or the
vendor block at all. Rewrote all five so each one restates the rules in its own
terms, names its tools and the ticket types it owns, states what is out of scope,
and ends with a worked example from a real ticket (~200 words each to ~470-640).

---

## Problem 6 — Plan the three tickets

> before you wire the backend, write down what you expect the team to do on each open ticket. Build output/desk_tickets.html - a page you can double-click with one tab per ticket (101, 102, and 103). Also add empty Cash and Reflection tabs for later problems (leave them blank or with a short "coming later" note for now). On each ticket tab, fill an Expected section only (leave room for an Actual section we will fill after the agents run)

Written before the backend was wired, so each Expected section is a prediction
rather than a description of a result. Every number in it comes from the
database as it stands at reset.

---

## Problem 7 — Backend routes

> your React frontend dashboard (the next problem) needs a backend it can call. In backend/main.py use FastAPI and add routes that do the following:
>
> * return the three tickets and whether each is open or resolved
> * take a ticket id and run your agent team on that ticket
> * return recent agent events - what each agent said and which tools they used - so the board can refresh
> * approve a payment or purchase after a human clicks approve (agents only prepare the pay, this route is what actually changes cash)
> * return the current checking balance from cash_accounts
> * reset the database to the original values when we want to try a fresh run

Running the routes live turned up a real bug: after rent was paid,
`get_cash_balance` still counted it as an upcoming obligation, so the balance
read as negative and the shop looked insolvent. Fixed by excluding leases that
already have a rent payment against them.

---

## Problem 8 — Agent dashboard

> build the frontend dashboard in frontend/ with React + Vite + TypeScript. The page should call the routes you built in problem 7. at minimum the board should:
>
> * List all three tickets
> * let you pick one ticket and start the agent team on it
> * show each agent and what they are saying / doing while the ticket runs
> * mark a ticket resolved when the run finishes
> * show a short summary of what each agent did on that ticket
> * let a human approve a pay or purchase when asked
> * show the checking balance (it should drop after an approved pay)

Driving the board in a browser caught two display bugs: the agent panel was
blending tool calls from different runs, and a finished run looked identical to
an untouched ticket.

**Follow-up**

> ok now we need to make the design better. a real human should want to use this dashboard. I think it needs to be minimalistic and easy to read while also being interesting

> i think this layout is confusing, how about we design it based on old school business ticketing systems, less reduce the wordiness and make it look not so AI generated or modern

> when I click on the different tickets is doesn't always show the case detail at the bottom, I want to be able to go between the three tickets and see the info

> lets move the activity log to the bottom of the screen

> lets use the font a little easier to read and not so small

> in case detail don't show the finding until the user click run agent team, and then show the findings in a box to the right of the case details

> I rejected the AI club ticket but the status went back to open after I ran the agents on another ticket

> after running the agents, don't update the case details notes sections, any new notes from the agents should be on the agent findings side

> I feel like the agent findings and updates sections are repetitive. do we really need the updates?

> when i ran the agent for ticket 101 it gave me to invoices to approve

> now for the ai club ticket, it didn't give me the option to approve anything

> tell the front end to talk to the backend at http://localhost:8000. On the backend, allow the Vite page origin (usually http://localhost:5173) so the browser is allowed to call those routes. Start the board with npm run dev

> write output/design.md with what we chose for the dashboard look (layout, how agents read differently, how resolved tickets and cash show up) and why - including the creative choices that make it feel special and something humans would actually enjoy using

> be slightly less wordy in design.md and use "i" instead of "we"

> I like the old fashioned layout style because I think people of all ages can use it instictively and understand it better

*What was lacking:* two tickets depend on the same invoice, and each was raising
its own approval for it — two cards for one $840 bill. Fixed by making approvals
per obligation rather than per ticket, propagating the decision to every
dependent ticket, and refusing at the pay tool any obligation already settled.

*What was lacking:* the board was honest about everything except ticket status —
the Boss did not always set one, declining a payment set none at all, and a
shared approval row updated only one of two tickets. All three are fixed in the
backend rather than in prompts.

*What was lacking:* the first board worked but read like a debug view — uniform
grey cards, raw tool names, and no sense of what mattered most. The redesign gave
it a typographic hierarchy, plain-language activity, and live states, and in the
process exposed duplicate approval cards and an Accounting loop that was burning
87 tool calls a run.

---

## Problem 9 — Resolve the tickets

> before testing the agents on a full run over the three tickets, reset the working database data/campus_customs_new.db again so you start clean. Then run all three tickets on the board until each is resolved

Follow-ups:

> open output/desk_tickets.html from problem 6. on each ticket tab fill the Actual section from this run: which agents worked, what they delegated, and which tools they used. Keep the Expected section so we can compare.

> on the Cash tab of the same output/desk_tickets.html, itemize the money: starting checking balance (after the reset), for each ticket how cash changed when that ticket resolved and why, ending checking balance - it must match cash_accounts in the working database

> wrong cash math loses points even if the board shows every ticket resolved. Also save output/resolved_tickets.json and output/resolved_board.html with a screenshot of the React board for each resolved ticket

> append real runs to output/audit_trail.json. Finish output/harness.md so it covers tables, MCP tools, the five agents, API routes, the dashboard, and safety rules

All three resolved on a clean pass. Balance $3,400.00 -> $160.00, both payments
authorised by a human, the discount approved without moving cash. Actual sections
filled in `output/desk_tickets.html` against the frozen plan, including the three
predictions that were wrong.

---

## Problem 10 — Reflection

> open output/desk_tickets.html and fill the Reflection tab. Answer the follow questions and be detailed and thorough. I'll provide my input for you to build on:
>
> * How would you evaluate the performance of the agents on each ticket and why? "I thought the agents did well distributing their work and moved quickly. They seemed to have the right recommendations"
> * For each ticket, how did Actual compare to the Expected plan I wrote earlier?
> * What would have been simpler as one agent with tools - and why?
> * Describe three new problems Campus Customs might face that this agent team could solve with the tools we built
> * Describe three new problems Campus Customs might face that this agent team could not solve with the tools we built and explain the tools and agents we would need to solve them

**Follow-up**

> tie every answer to this app and the three tickets we ran - use the ticket tabs and cash tab on the same page as your evidence. Genereric AI essays without Campus Customs details will score low

> incorporate my answer into your answer

*What was lacking:* the first draft quoted my assessment and then argued
alongside it, and leaned on general multi-agent reasoning in places. The rewrite
made my three claims — good distribution, quick, right recommendations — the
structure of the answer, and tied every section to the 101, 102 and 103 tabs and
the Cash tab figures.

Writing the reflection exposed a real defect and led to a fix:

> why did customer service agent never get used?

> for the customer service agents lets fix the prompt

The Boss's completion checklist never required a customer reply, so all three
tickets closed with the requester told nothing. Fixed in `boss.md` and
`customer_service.md`; the fix also surfaced duplicate drafts and a
39-call save loop, both fixed in the tool layer.

---

## Problem 11 — Submit to GitHub

> push Homework-5 code to a public GitHub repository so graders can clone it. Submit the repo URL and also put it in output/github_url.txt

> do not push my real .env to the GitHyb repo

> do include both database files under data/ (the original and our working copy) so graders can run the app easily

**Repository:** <https://github.com/hodgeke10/mgt403-hw5-campus-customs>

Verified before pushing that no `.env`, `.venv`, or `node_modules` was staged and
that no secret-shaped string appeared anywhere in the staged content, and
verified after pushing by cloning the public repo into a clean directory: 52
files, no `.env`, and the database opens at $3,400.00 with three open tickets.

<!--
TEMPLATE for each remaining problem:

## Problem N — <title>

> <prompt>

**Follow-up**

> <follow-up prompt>

*What was lacking:* <one sentence>
-->
