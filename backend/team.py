"""The Campus Customs agent team — five roles, full connectivity.

Every agent runs on the same model (`gpt-6-luna` via Portkey) and shares the
same MCP toolset, so the shop rules enforced in the tools hold no matter who
calls them.

Connectivity: each agent gets a `delegate` tool that can reach every other
agent, including the Boss. Delegation is depth-limited and loop-guarded so a
pair of agents cannot bounce the same question back and forth forever.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext, UsageLimits

import audit
from config import MODEL_NAME, MODEL_SETTINGS, build_model, load_prompt, mcp_toolset
from models import AgentReply, Role, TicketDecision

MAX_DEPTH = 3
# Shared across a whole delegation chain, not per agent — a Boss run that
# consults two specialists spends from the same budget.
USAGE_LIMITS = UsageLimits(request_limit=60, tool_calls_limit=90)

ROLE_BLURBS = {
    Role.BOSS: "reads tickets, routes work, makes the final call",
    Role.INVENTORY: "stock by SKU and size, shortfalls, which vendor can restock",
    Role.ACCOUNTING: "cash, invoices, margins, payments prepared for approval",
    Role.FACILITIES: "the shop space — leases, rent, the landlord",
    Role.CUSTOMER_SERVICE: "drafts messages to the person who filed the ticket",
}


@dataclass
class TeamDeps:
    """Shared state for one ticket's run.

    `run_id` and `actor` travel down into delegated sub-runs so every tool call
    in the audit trail is attributed to the agent that actually made it.
    """

    ticket_id: int | None = None
    depth: int = 0
    trail: tuple[Role, ...] = ()
    transcript: list[dict] = field(default_factory=list)
    run_id: str = ""
    actor: str = "boss"
    # Shared across the whole run, including delegated sub-runs, so two agents
    # asking the same read-only question pay for it once.
    tool_cache: dict = field(default_factory=dict)

    def child(self, caller: Role, target: Role) -> TeamDeps:
        """Deps for a delegated sub-run, one level deeper."""
        return TeamDeps(
            ticket_id=self.ticket_id,
            depth=self.depth + 1,
            trail=self.trail + (caller,),
            transcript=self.transcript,
            run_id=self.run_id,
            actor=target.value,
            tool_cache=self.tool_cache,
        )


def _roster(exclude: Role) -> str:
    """The teammate list injected into each agent's prompt."""
    return "\n".join(
        f"- `{r.value}` — {ROLE_BLURBS[r]}" for r in Role if r is not exclude
    )


def _build_agent(role: Role, output_type: type) -> Agent[TeamDeps, object]:
    """Create one agent: shared model, shared MCP tools, plus delegation."""
    shared = load_prompt("_shared")
    own = load_prompt(role.value)

    agent = Agent(
        build_model(),
        deps_type=TeamDeps,
        output_type=output_type,
        toolsets=[mcp_toolset()],
        model_settings=MODEL_SETTINGS,
        system_prompt=f"{own}\n\n---\n\n{shared}",
    )

    @agent.system_prompt
    def teammates(ctx: RunContext[TeamDeps]) -> str:
        """Tell the agent who it can delegate to, and how deep it already is."""
        remaining = MAX_DEPTH - ctx.deps.depth
        if remaining <= 0:
            return (
                "You have reached the delegation limit. Answer from your own "
                "tools and knowledge; the `delegate` tool will refuse."
            )
        trail = " -> ".join(r.value for r in ctx.deps.trail) or "(none)"
        return (
            f"## Your teammates\n\n{_roster(role)}\n\n"
            f"Delegation chain so far: {trail}. "
            f"You may delegate {remaining} more level(s) deep."
        )

    @agent.tool
    async def delegate(ctx: RunContext[TeamDeps], teammate: str, question: str) -> dict:
        """Ask another agent a question in their area and get their findings back.

        `teammate` must be one of: boss, inventory, accounting, facilities,
        customer_service. Ask one specific question; do not re-ask the same one.
        """
        try:
            target = Role(teammate.strip().lower())
        except ValueError:
            return {
                "error": f"Unknown teammate {teammate!r}.",
                "valid": [r.value for r in Role],
            }

        if target is role:
            return {"error": "You cannot delegate to yourself — answer it directly."}
        if ctx.deps.depth >= MAX_DEPTH:
            return {
                "error": "Delegation depth limit reached. Answer from your own tools.",
                "depth": ctx.deps.depth,
            }
        if target in ctx.deps.trail:
            return {
                "error": (
                    f"{target.value} is already working further up this chain; "
                    "answering again would loop. Use what you have."
                ),
                "chain": [r.value for r in ctx.deps.trail],
            }

        ctx.deps.transcript.append(
            {"from": role.value, "to": target.value, "question": question}
        )
        audit.record(ctx.deps.run_id, "delegation", role.value, ctx.deps.ticket_id,
                     target=target.value, detail={"question": question,
                                                  "depth": ctx.deps.depth})
        reply = await TEAM[target].run(
            question,
            deps=ctx.deps.child(role, target),
            usage=ctx.usage,
            usage_limits=USAGE_LIMITS,
        )
        out: AgentReply = reply.output
        ctx.deps.transcript.append(
            {"from": target.value, "to": role.value, "answer": out.answer}
        )
        audit.record(ctx.deps.run_id, "delegation_reply", target.value,
                     ctx.deps.ticket_id, target=role.value,
                     detail={"blocked_by": out.blocked_by,
                             "approvals": len(out.approvals_needed)},
                     result=out.answer)
        return out.model_dump(mode="json")

    return agent


# Specialists return AgentReply; the Boss returns a full TicketDecision.
TEAM: dict[Role, Agent[TeamDeps, object]] = {}


def build_team() -> dict[Role, Agent[TeamDeps, object]]:
    """Build all five agents once and wire them to each other."""
    if TEAM:
        return TEAM
    for role in Role:
        TEAM[role] = _build_agent(
            role, TicketDecision if role is Role.BOSS else AgentReply
        )
    return TEAM


async def run_ticket(ticket_id: int, instruction: str = "") -> dict:
    """Run one ticket through the Boss, who delegates as needed.

    Returns the Boss's decision plus the delegation transcript, so the dashboard
    can show who was consulted and what they said.
    """
    build_team()
    run_id = audit.new_run_id()
    deps = TeamDeps(
        ticket_id=ticket_id, trail=(Role.BOSS,), run_id=run_id, actor=Role.BOSS.value
    )
    task = instruction or (
        f"Handle ticket {ticket_id}. Read it with the tools available, delegate "
        "the parts that belong to a specialist, and give your decision. List "
        "any payment as pending human approval — never as done."
    )
    audit.record(run_id, "run_started", Role.BOSS.value, ticket_id,
                 detail={"task": task, "model": MODEL_NAME})
    try:
        result = await TEAM[Role.BOSS].run(task, deps=deps, usage_limits=USAGE_LIMITS)
    except Exception as exc:
        audit.record(run_id, "run_failed", Role.BOSS.value, ticket_id,
                     result={"error": f"{type(exc).__name__}: {exc}"})
        raise

    decision = result.output.model_dump(mode="json")
    audit.record(run_id, "run_finished", Role.BOSS.value, ticket_id,
                 detail={"consulted": decision.get("consulted"),
                         "delegation_steps": len(deps.transcript),
                         "approvals_needed": len(decision.get("approvals_needed", [])),
                         "usage": str(result.usage)},
                 result=decision)
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "decision": decision,
        "delegations": deps.transcript,
    }


async def ask(role: Role, question: str, ticket_id: int | None = None) -> dict:
    """Ask one agent directly — used for testing a single role."""
    build_team()
    run_id = audit.new_run_id()
    deps = TeamDeps(ticket_id=ticket_id, trail=(role,), run_id=run_id, actor=role.value)
    audit.record(run_id, "run_started", role.value, ticket_id,
                 detail={"question": question, "model": MODEL_NAME, "direct": True})
    result = await TEAM[role].run(question, deps=deps, usage_limits=USAGE_LIMITS)
    audit.record(run_id, "run_finished", role.value, ticket_id,
                 result=result.output.model_dump(mode="json"))
    return {
        "run_id": run_id,
        "role": role.value,
        "output": result.output.model_dump(mode="json"),
        "delegations": deps.transcript,
    }


if __name__ == "__main__":
    import json
    import sys

    tid = int(sys.argv[1]) if len(sys.argv) > 1 else 101
    print(json.dumps(asyncio.run(run_ticket(tid)), indent=2))
