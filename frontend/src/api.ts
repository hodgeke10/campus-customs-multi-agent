/** Typed calls to the FastAPI backend (proxied through /api by Vite). */

export type Ticket = {
  id: number
  type: string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  status: string
  is_open: boolean
  notes: string | null
  created_at: string
}

export type Approval = {
  id: number
  ticket_id: number | null
  kind: string
  ref_id: number | null
  payee: string
  amount: number
  account: string
  reason: string | null
  requested_by: string
  status: 'pending' | 'approved' | 'declined'
  decided_by: string | null
  payment_id: number | null
}

export type AgentEvent = {
  ts: string
  run_id: string
  ticket_id: number | null
  step: string
  actor: string
  target: string | null
  detail: unknown
  result: unknown
}

export type Cash = {
  account: string
  balance: number
  open_invoice_total: number
  upcoming_rent_total: number
  total_known_obligations: number
  balance_after_all_obligations: number
  covers_all_obligations: boolean
}

export type Decision = {
  ticket_id: number
  summary: string
  decision: string
  blocked_by: string
  consulted: string[]
  approvals_needed: unknown[]
  draft: { audience: string; subject: string; body: string; check_before_sending: string } | null
  next_step: string
}

export type Run = {
  status: 'running' | 'finished' | 'failed'
  ticket_id: number
  run_id?: string
  decision?: Decision
  delegations?: { from: string; to: string; question?: string; answer?: string }[]
  error?: string
}

/** The FastAPI backend from problem 7. Override with VITE_API_BASE if it moves. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  tickets: () => call<{ shop_today: string; open_count: number; tickets: Ticket[] }>('/tickets'),
  cash: () => call<Cash>('/cash'),
  approvals: () => call<{ approvals: Approval[] }>('/approvals'),
  events: (limit = 200) => call<{ events: AgentEvent[] }>(`/events?limit=${limit}`),
  run: (id: number) =>
    call<{ run_key: string }>(`/tickets/${id}/run`, { method: 'POST', body: '{}' }),
  runStatus: (key: string) => call<Run>(`/runs/${key}`),
  approve: (id: number, decided_by: string) =>
    call<{ paid: boolean; payment: Record<string, unknown> }>(`/approvals/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ decided_by }),
    }),
  decline: (id: number, decided_by: string) =>
    call<unknown>(`/approvals/${id}/decline`, {
      method: 'POST',
      body: JSON.stringify({ decided_by }),
    }),
  reset: () => call<{ reset: boolean }>('/reset', { method: 'POST' }),
}
