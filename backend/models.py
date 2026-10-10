"""Data types for the Campus Customs agent team.

Structured outputs keep the agents honest: an approval request has to name an
amount and a payee, and a payment proposal has nowhere to record itself as
"paid", because only a human can decide that.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    """The five agents on the team. Any role may delegate to any other."""

    BOSS = "boss"
    INVENTORY = "inventory"
    ACCOUNTING = "accounting"
    FACILITIES = "facilities"
    CUSTOMER_SERVICE = "customer_service"


class ApprovalStatus(str, Enum):
    """Where a proposed payment stands. Agents may only ever set PENDING."""

    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


class ApprovalRequest(BaseModel):
    """A payment an agent wants a human to approve. Never self-approved."""

    kind: str = Field(description="What is being paid, e.g. 'invoice' or 'rent'.")
    payee: str = Field(description="Who receives the money, from the database.")
    amount: float = Field(description="Amount in dollars, from a tool result.")
    account: str = Field(default="checking", description="Account it would come from.")
    reason: str = Field(description="Why this payment is needed, in one sentence.")
    ref_id: int | None = Field(
        default=None, description="Invoice or lease id this settles, if any."
    )
    balance_after: float | None = Field(
        default=None, description="Balance remaining if approved."
    )
    status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING,
        description="Always 'pending' when an agent creates it.",
    )


class Draft(BaseModel):
    """A customer message that stays on the board. Nothing is ever sent."""

    audience: str = Field(description="Who the message is addressed to.")
    subject: str
    body: str
    check_before_sending: str = Field(
        default="",
        description="Anything a human should confirm before this goes out.",
    )


class AgentReply(BaseModel):
    """What a specialist hands back when a teammate delegates to it."""

    role: Role
    answer: str = Field(description="The findings, with the numbers that support them.")
    facts_used: list[str] = Field(
        default_factory=list,
        description="Tool-sourced values behind the answer, e.g. 'on_hand=8'.",
    )
    blocked_by: str = Field(
        default="", description="What prevents this from moving, if anything."
    )
    approvals_needed: list[ApprovalRequest] = Field(default_factory=list)
    draft: Draft | None = None


class TicketDecision(BaseModel):
    """The Boss's final call on a ticket."""

    ticket_id: int
    summary: str = Field(description="What is true about this ticket, with numbers.")
    decision: str = Field(description="The specific action being taken or recommended.")
    blocked_by: str = Field(
        default="", description="What stops this ticket, including another ticket."
    )
    consulted: list[Role] = Field(
        default_factory=list, description="Teammates the Boss delegated to."
    )
    approvals_needed: list[ApprovalRequest] = Field(
        default_factory=list,
        description="Every payment awaiting a human. Empty if none.",
    )
    draft: Draft | None = Field(
        default=None, description="Customer message, if one was written."
    )
    next_step: str = Field(description="What happens once any approval is decided.")
