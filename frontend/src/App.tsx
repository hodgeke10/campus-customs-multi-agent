import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type AgentEvent,
  type Approval,
  type Cash,
  type Decision,
  type Run,
  type Ticket,
} from './api'
import './App.css'

const AGENTS = ['boss', 'inventory', 'accounting', 'facilities', 'customer_service'] as const
const LABEL: Record<string, string> = {
  boss: 'BOSS',
  inventory: 'INVENTORY',
  accounting: 'ACCOUNTING',
  facilities: 'FACILITIES',
  customer_service: 'CUST SERVICE',
  human: 'OPERATOR',
}
const CODE: Record<string, string> = {
  open: 'OPEN',
  blocked: 'BLOCKED',
  awaiting_approval: 'HOLD-APPR',
  resolved: 'CLOSED',
  pending: 'PENDING',
}
const ACTION: Record<string, string> = {
  get_ticket: 'READ TICKET',
  list_tickets: 'LIST BOARD',
  check_stock: 'STOCK CHECK',
  check_vendor_availability: 'VENDOR CHECK',
  get_pricing: 'PRICE CHECK',
  get_cash_balance: 'CASH CHECK',
  list_invoices: 'INVOICE LIST',
  get_rent_status: 'RENT CHECK',
  request_payment_approval: 'QUEUE PAYMENT',
  list_approvals: 'APPR LIST',
  pay_approved: 'SETTLE PAYMENT',
  create_purchase_order: 'RAISE PO',
  save_customer_draft: 'SAVE DRAFT',
  update_ticket_status: 'SET STATUS',
}

/** Agents and the approval routes append stamped lines to tickets.notes:
 *  "[2026-08-31 boss] ...". The case record should keep showing only what the
 *  requester actually wrote; everything stamped belongs with the findings. */
const STAMP = /^\[\d{4}-\d{2}-\d{2} ([^\]]+)\]/
/** Agents and the backend restate their own findings into the ticket note, which
 *  the findings panel already shows. Only a human decision adds something the
 *  board cannot show anywhere else. */
const RESTATERS = new Set([
  'boss', 'inventory', 'accounting', 'facilities', 'customer service', 'backend',
])
function splitNotes(notes: string | null): { original: string; log: string[] } {
  if (!notes) return { original: '', log: [] }
  const original: string[] = []
  const log: string[] = []
  for (const line of notes.split('\n')) {
    const m = STAMP.exec(line.trim())
    if (!m) { original.push(line); continue }
    if (!RESTATERS.has(m[1].trim().toLowerCase())) log.push(line)
  }
  return { original: original.join('\n').trim(), log }
}

const money = (n: number) =>
  n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const clock = (ts: string) => ts.slice(11, 19)

type AgentState = {
  role: string
  active: boolean
  state: string
  calls: number
  said: string | null
}

function deriveAgents(events: AgentEvent[], running: boolean): AgentState[] {
  const map = new Map<string, AgentState>()
  AGENTS.forEach(r => map.set(r, { role: r, active: false, state: 'IDLE', calls: 0, said: null }))
  let last = ''
  for (const e of events) {
    const s = map.get(e.actor)
    if (!s) continue
    last = e.actor
    if (e.step === 'tool_call') {
      s.calls++
      s.state = ACTION[e.target ?? ''] ?? 'WORKING'
    } else if (e.step === 'delegation') s.state = `-> ${LABEL[e.target ?? ''] ?? e.target}`
    else if (e.step === 'delegation_reply') {
      s.state = 'REPORTED'
      if (typeof e.result === 'string') s.said = e.result
    } else if (e.step === 'run_started') s.state = 'ASSIGNED'
    else if (e.step === 'run_finished') s.state = 'DECIDED'
  }
  if (running && last) {
    const s = map.get(last)
    if (s) {
      s.active = true
      s.state = s.state === 'IDLE' ? 'WORKING' : s.state
    }
  }
  return AGENTS.map(r => map.get(r)!)
}

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [shopToday, setShopToday] = useState('')
  const [cash, setCash] = useState<Cash | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [runKey, setRunKey] = useState<string | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState(false)
  const prevBalance = useRef<number | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const running = run?.status === 'running'

  const refresh = useCallback(async () => {
    try {
      const [t, c, a, e] = await Promise.all([
        api.tickets(), api.cash(), api.approvals(), api.events(),
      ])
      setTickets(t.tickets)
      setShopToday(t.shop_today)
      // Land on the first ticket so the detail pane is never blank on open.
      setSelected(prev => prev ?? t.tickets[0]?.id ?? null)
      if (prevBalance.current !== null && c.balance !== prevBalance.current) {
        setFlash(true)
        setTimeout(() => setFlash(false), 2000)
      }
      prevBalance.current = c.balance
      setCash(c)
      setApprovals(a.approvals)
      setEvents(e.events)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  useEffect(() => {
    if (!runKey) return
    let stop = false
    const tick = async () => {
      try {
        const status = await api.runStatus(runKey)
        if (stop) return
        setRun(status)
        await refresh()
        if (status.status === 'running') setTimeout(tick, 2000)
        else setBusy(false)
      } catch (err) {
        if (!stop) { setError(err instanceof Error ? err.message : String(err)); setBusy(false) }
      }
    }
    void tick()
    return () => { stop = true }
  }, [runKey, refresh])

  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight }) }, [events])

  /** The last finished decision per ticket, read back from the audit trail so
   *  browsing between tickets still works after a page reload. */
  const decisions = useMemo(() => {
    // Only runs since the last database reset count. After a reset the shop is
    // back to its opening state, so findings from an earlier run describe a
    // world that no longer exists.
    const lastReset = events.map(e => e.step).lastIndexOf('database_reset')
    const live = lastReset === -1 ? events : events.slice(lastReset + 1)
    const out: Record<number, Decision> = {}
    for (const e of live) {
      if (e.step === 'run_finished' && e.ticket_id && e.result && typeof e.result === 'object') {
        out[e.ticket_id] = e.result as Decision
      }
    }
    return out
  }, [events])

  /** The run whose events are on screen: the live one, else the most recent run
   *  for whichever ticket is selected. Selecting a ticket moves the whole board. */
  const runEvents = useMemo(() => {
    if (run?.run_id) return events.filter(e => e.run_id === run.run_id)
    const lastReset = events.map(e => e.step).lastIndexOf('database_reset')
    const live = lastReset === -1 ? events : events.slice(lastReset + 1)
    const forTicket = live.filter(
      e =>
        e.run_id &&
        !e.run_id.startsWith('human-') &&
        e.run_id !== 'reset' &&
        (selected === null || e.ticket_id === selected),
    )
    const id = forTicket[forTicket.length - 1]?.run_id
    return id ? events.filter(e => e.run_id === id) : []
  }, [events, run, selected])

  const agents = useMemo(() => deriveAgents(runEvents, running), [runEvents, running])
  const pending = approvals.filter(a => a.status === 'pending')
  const ticket = tickets.find(t => t.id === selected) ?? null
  const decision = ticket ? decisions[ticket.id] ?? null : null
  const notes = splitNotes(ticket?.notes ?? null)

  async function startRun() {
    if (selected === null) return
    setBusy(true); setError(null)
    setRun({ status: 'running', ticket_id: selected })
    setSelected(selected)
    try {
      const { run_key } = await api.run(selected)
      setRunKey(run_key)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err)); setBusy(false); setRun(null)
    }
  }

  async function decide(id: number, ok: boolean) {
    setBusy(true)
    try {
      if (ok) await api.approve(id, 'operator'); else await api.decline(id, 'operator')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy(false) }
  }

  async function reset() {
    setBusy(true)
    try {
      await api.reset(); setRun(null); setRunKey(null); await refresh()
    } finally { setBusy(false) }
  }

  return (
    <div className="term">
      <div className="titlebar">
        <span className="sys">CAMPUS CUSTOMS</span>
        <span className="mod">OPERATIONS DESK v1.0</span>
        <span className="spacer" />
        <span className="field">DATE <b>{shopToday || '--------'}</b></span>
        <span className="field">USER <b>OPERATOR</b></span>
        <span className="field">AGENTS <b>{running ? 'RUNNING' : 'IDLE'}</b></span>
      </div>

      <div className="toolbar">
        <button onClick={startRun} disabled={busy || running || selected === null}>
          Run Agent Team
        </button>
        <button onClick={() => void refresh()} disabled={busy}>Refresh</button>
        <button onClick={reset} disabled={busy}>Reset Data</button>
        <span className="spacer" />
        <span className="ledger">
          CHECKING <b className={flash ? 'flash' : ''}>{cash ? money(cash.balance) : '--'}</b>
          <i>OWED {cash ? money(cash.total_known_obligations) : '--'}</i>
        </span>
      </div>

      {error && <div className="alert">** {error}</div>}

      <div className="grid">
        {/* ------------------------------------------------ ticket queue */}
        <section className="pane wide">
          <div className="cap">Ticket Queue</div>
          <table className="grid-table">
            <thead>
              <tr>
                <th style={{ width: 52 }}>TKT</th>
                <th style={{ width: 112 }}>TYPE</th>
                <th style={{ width: 150 }}>REQUESTER</th>
                <th>SUBJECT</th>
                <th style={{ width: 130 }}>ITEM</th>
                <th style={{ width: 86 }}>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <tr
                  key={t.id}
                  className={selected === t.id ? 'sel' : ''}
                  onClick={() => setSelected(t.id)}
                >
                  <td>{t.id}</td>
                  <td>{t.type.replace('_', ' ').toUpperCase()}</td>
                  <td>{t.requester}</td>
                  <td>{t.subject}</td>
                  <td>{t.sku ? `${t.qty}x ${t.sku} ${t.size ?? ''}` : '--'}</td>
                  <td className={`st ${t.status}`}>{CODE[t.status] ?? t.status.toUpperCase()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="statusline">
            {tickets.length} RECORD(S) &middot; {tickets.filter(t => t.is_open).length} OPEN
            {selected !== null && <> &middot; SELECTED TKT {selected}</>}
          </div>
        </section>

        {/* ------------------------------------------------ agents */}
        <section className="pane">
          <div className="cap">Agent Status</div>
          <table className="grid-table">
            <thead>
              <tr>
                <th style={{ width: 108 }}>AGENT</th>
                <th>STATE</th>
                <th style={{ width: 40 }}>OPS</th>
              </tr>
            </thead>
            <tbody>
              {agents.map(a => (
                <tr key={a.role} className={a.active ? 'on' : a.calls ? '' : 'dim'}>
                  <td>{LABEL[a.role]}</td>
                  <td className="state">{a.active && <i className="blip" />}{a.state}</td>
                  <td className="num">{a.calls || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* ------------------------------------------------ approvals */}
        <section className="pane">
          <div className="cap">Pending Authorisation</div>
          {pending.length === 0 ? (
            <div className="none">NO ITEMS AWAITING AUTHORISATION</div>
          ) : (
            <table className="grid-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}>ID</th>
                  <th style={{ width: 60 }}>TYPE</th>
                  <th>PAYEE</th>
                  <th style={{ width: 76 }} className="num">AMOUNT</th>
                  <th style={{ width: 128 }}>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {pending.map(a => (
                  <tr key={a.id}>
                    <td>{a.id}</td>
                    <td>{a.kind.toUpperCase()}</td>
                    <td>{a.payee}</td>
                    <td className="num">{money(a.amount)}</td>
                    <td className="act">
                      <button className="sm" disabled={busy} onClick={() => decide(a.id, true)}>
                        Authorise
                      </button>
                      <button className="sm" disabled={busy} onClick={() => decide(a.id, false)}>
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* ------------------------------------------------ detail */}
        <section className="pane wide">
          <div className="cap">
            Case Detail
            {ticket && <span>TKT {ticket.id} &middot; {CODE[ticket.status] ?? ticket.status}</span>}
          </div>
          {!ticket && <div className="none">SELECT A TICKET</div>}
          {ticket && (
            <div className="detail">
              <dl className="rec">
                <dt>SUBJECT</dt><dd>{ticket.subject}</dd>
                <dt>REQUESTER</dt><dd>{ticket.requester}</dd>
                <dt>FILED</dt><dd>{ticket.created_at.slice(0, 16).replace('T', ' ')}</dd>
                <dt>ITEM</dt>
                <dd>{ticket.sku ? `${ticket.qty} x ${ticket.sku} ${ticket.size ?? ''}` : '--'}</dd>
                <dt>TYPE</dt><dd>{ticket.type.replace('_', ' ').toUpperCase()}</dd>
                <dt>STATUS</dt>
                <dd className={`st ${ticket.status}`}>{CODE[ticket.status] ?? ticket.status}</dd>
                <dt>NOTES</dt>
                <dd>{notes.original || <span className="muted">--</span>}</dd>
              </dl>

              {/* Findings stay hidden until the agent team has actually run on
                  this ticket — an empty findings box reads like a conclusion. */}
              <div className="findings">
                <div className="fcap">
                  Agent Findings
                  {decision && <span>{decision.consulted.map(c => LABEL[c] ?? c).join(', ')}</span>}
                </div>

                {!decision && notes.log.length === 0 && (
                  <div className="await">
                    {running && run?.ticket_id === ticket.id ? (
                      <span><i className="blip" />AGENT TEAM RUNNING...</span>
                    ) : (
                      <>
                        NO AGENT RUN ON THIS TICKET
                        <span>SELECT IT AND PRESS "RUN AGENT TEAM"</span>
                      </>
                    )}
                  </div>
                )}

                {!decision && notes.log.length > 0 && (
                  <dl className="rec inner">
                    <dt>AUTHORISATION</dt>
                    <dd className="updates">
                      {notes.log.map((l, i) => <div key={i}>{l}</div>)}
                    </dd>
                  </dl>
                )}

                {decision && (
                  <dl className="rec inner">
                    <dt>FINDINGS</dt><dd>{decision.summary}</dd>
                    <dt>DECISION</dt><dd>{decision.decision}</dd>
                    {decision.blocked_by && (
                      <><dt>BLOCKED</dt><dd className="bad">{decision.blocked_by}</dd></>
                    )}
                    <dt>NEXT</dt><dd>{decision.next_step}</dd>
                    {notes.log.length > 0 && (
                      <>
                        <dt>AUTHORISATION</dt>
                        <dd className="updates">
                          {notes.log.map((l, i) => <div key={i}>{l}</div>)}
                        </dd>
                      </>
                    )}
                    {decision.draft && (
                      <>
                        <dt>DRAFT<br /><span className="sub">NOT SENT</span></dt>
                        <dd className="draft">
                          <b>RE: {decision.draft.subject}</b>
                          {decision.draft.body}
                        </dd>
                      </>
                    )}
                  </dl>
                )}
              </div>
            </div>
          )}
        </section>
        {/* ------------------------------------------------ log */}
        <section className="pane wide log-pane">
          <div className="cap">
            Activity Log {runEvents.length > 0 && <span>TKT {runEvents[0]?.ticket_id ?? '--'}</span>}
          </div>
          <div className="log" ref={logRef}>
            {runEvents.length === 0 && <div className="none">NO ACTIVITY</div>}
            {runEvents.map((e, i) => (
              <div key={i} className={`ln ${e.step}`}>
                <span className="t">{clock(e.ts)}</span>
                <span className="a">{LABEL[e.actor] ?? e.actor.toUpperCase()}</span>
                <span className="m">
                  {e.step === 'tool_call' && (ACTION[e.target ?? ''] ?? e.target?.toUpperCase())}
                  {e.step === 'delegation' && `ASSIGN -> ${LABEL[e.target ?? ''] ?? e.target}`}
                  {e.step === 'delegation_reply' && `REPORT -> ${LABEL[e.target ?? ''] ?? e.target}`}
                  {e.step === 'run_started' && 'TICKET ASSIGNED'}
                  {e.step === 'run_finished' && 'RUN COMPLETE'}
                  {e.step === 'run_failed' && 'RUN ABORTED'}
                  {e.step === 'human_approval' && 'PAYMENT AUTHORISED'}
                  {e.step === 'human_decline' && 'PAYMENT REJECTED'}
                  {e.step === 'database_reset' && 'DATA RESET'}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="statusbar">
        <span>MCP: CAMPUS-CUSTOMS-OPS</span>
        <span>MODEL: GPT-6-LUNA</span>
        <span>DB: CAMPUS_CUSTOMS_NEW</span>
        <span className="spacer" />
        <span>{running ? 'PROCESSING...' : 'READY'}</span>
      </div>
    </div>
  )
}
