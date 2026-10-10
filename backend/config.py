"""Model and MCP wiring for the Campus Customs agent team.

Project code reaches OpenAI through Portkey. The model id is defined once here
and shared by all five agents.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
WORKSPACE = PROJECT.parents[1]

# The workspace-root .env is the real credential store on the machine this was
# built on. A standalone clone of this project has no workspace above it, so a
# project-level .env is accepted as a fallback — see .env.example.
load_dotenv(WORKSPACE / ".env")
load_dotenv(PROJECT / ".env")

# Required model for this assignment — overrides the workspace default.
MODEL_NAME = "gpt-6-luna"

PROMPTS_DIR = HERE / "prompts"

# The MCP server lives alongside the backend; attach it in-process so there is
# no second terminal to run and both share one view of the working database.
MCP_DIR = PROJECT / "mcp_server"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))


# gpt-6-luna rejects function tools on /chat/completions unless reasoning
# effort is 'none'. Every agent here calls MCP tools, so this is required.
MODEL_SETTINGS = OpenAIChatModelSettings(openai_reasoning_effort="none")


def build_model() -> OpenAIChatModel:
    """Create the shared gpt-6-luna model routed through Portkey."""
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("PORTKEY_API_KEY is missing from the workspace-root .env file.")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1"),
        default_headers={"x-portkey-api-key": api_key},
    )
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# Tools a human uses, never an agent. Excluded from the agents' toolset so no
# agent can approve its own payment — the gate in pay_approved is only real if
# nothing on the agent side can flip an approval to 'approved'.
HUMAN_ONLY_TOOLS = {"decide_approval"}

_toolset: MCPToolset | None = None


# Read-only tools whose answer cannot change inside a single run. Agents
# working the same ticket re-ask these constantly, which burns tool calls and
# tokens without adding information, so the first answer is reused.
_CACHEABLE = {
    "get_ticket", "list_tickets", "check_stock", "check_vendor_availability",
    "get_pricing", "get_rent_status", "list_invoices", "get_cash_balance",
}


async def _audited_call(ctx, call_tool, name: str, tool_args: dict):
    """Record every MCP tool call to the audit trail, then run it."""
    import audit  # local import keeps config importable without the backend

    deps = getattr(ctx, "deps", None)
    run_id = getattr(deps, "run_id", "unattributed")
    actor = getattr(deps, "actor", "unknown")
    ticket_id = getattr(deps, "ticket_id", None)

    cache = getattr(deps, "tool_cache", None)
    key = (name, repr(sorted(tool_args.items())))
    if cache is not None and name in _CACHEABLE and key in cache:
        audit.record(run_id, "tool_call", actor, ticket_id, target=name,
                     detail={**tool_args, "cached": True}, result="(reused earlier answer)")
        return cache[key]

    try:
        result = await call_tool(name, tool_args)
    except Exception as exc:
        audit.record(run_id, "tool_call", actor, ticket_id, target=name,
                     detail=tool_args, result={"error": str(exc)})
        raise
    audit.record(run_id, "tool_call", actor, ticket_id, target=name,
                 detail=tool_args, result=getattr(result, "data", result))
    if cache is not None and name in _CACHEABLE:
        cache[key] = result
    return result


def mcp_toolset():
    """Attach the campus-customs-ops FastMCP server in-process.

    Every agent shares this one toolset, so the shop rules enforced in the tools
    apply no matter which agent makes the call.
    """
    global _toolset
    if _toolset is None:
        from server import mcp as campus_mcp  # noqa: PLC0415  (path set above)

        _toolset = MCPToolset(
            campus_mcp, process_tool_call=_audited_call
        ).filtered(
            lambda ctx, tool: tool.name not in HUMAN_ONLY_TOOLS
        )
    return _toolset


def load_prompt(name: str) -> str:
    """Read an agent's system prompt from backend/prompts/."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing system prompt: {path}")
    return path.read_text(encoding="utf-8")
