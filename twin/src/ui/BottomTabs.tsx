import { money, useStore } from '../store'
import { STATUS_LABEL, TASK_LABEL, TASK_STATE_LABEL } from '../layout'
import type { AuditRow, Selection } from '../types'

export function auditTarget(a: AuditRow): Selection {
  if (a.task) return { kind: 'task', id: a.task }
  if (a.slot) return { kind: 'slot', id: a.slot }
  if (a.camera) return { kind: 'camera', id: a.camera }
  return { kind: 'agent', id: a.agent }
}

export function auditText(a: AuditRow): string {
  switch (a.action) {
    case 'route':
      return `Routed work to ${String(a.to).replace('_', ' ').replace('__end__', 'end of frame')}.`
    case 'detect':
      return `${a.camera}: ${a.boxes} boxes from ${String(a.source ?? '')}${a.boxes === 0 ? '' : ''}`.replace(/from $/, '').trim() + '.'
    case 'match_planogram': {
      const f = a.faults ?? {}
      const parts = Object.entries(f).filter(([, n]) => n).map(([k, n]) => `${n} ${STATUS_LABEL[k as keyof typeof STATUS_LABEL].toLowerCase()}`)
      return `${a.camera}: ${parts.length ? parts.join(', ') : 'all slots as planned'}${a.occluded ? `, ${a.occluded} hidden by shoppers` : ''}.`
    }
    case 'score':
      return `Compliance ${((a.compliance ?? 0) * 100).toFixed(0)}%, OSA ${((a.osa ?? 0) * 100).toFixed(0)}%, ${a.new_findings} new finding${a.new_findings === 1 ? '' : 's'}.`
    case 'propose_task':
      return `${a.task}: ${TASK_LABEL[a.type as keyof typeof TASK_LABEL]} ${a.sku} at ${a.slot}, priority ${a.priority}${a.review === 'pending' ? `, needs review (conf ${(a.confidence ?? 0).toFixed(2)})` : ''}.`
    case 'decide':
      return `${a.task} ${a.approved ? 'approved' : 'rejected'} by the reviewer.`
    case 'check_stock':
      return `${a.task}: ${a.qty} x ${a.sku} from ${a.source ?? 'nowhere'}.`
    case 'raise_replenishment':
      return `${a.request}: ${a.qty} x ${a.sku} requested from supply planning (${money(a.value)}).`
    default:
      return a.action
  }
}

export function AuditRowView({ a, onPick }: { a: AuditRow; onPick: (s: Selection) => void }) {
  const tone = a.action === 'decide' ? (a.approved ? 'good' : 'bad') : a.action === 'raise_replenishment' ? 'warn' : a.action === 'propose_task' ? 'info' : ''
  return (
    <div className={`feed-row ${tone}`} onClick={() => onPick(auditTarget(a))}>
      <span className="ts">fr {a.frame ?? '-'}</span>
      <span className="actor">{a.agent.replace('_', ' ')}</span>
      <span className="text">{auditText(a)}</span>
    </div>
  )
}

export function BottomTabs() {
  const snap = useStore((s) => s.snap!)
  const tab = useStore((s) => s.tab)
  const setTab = useStore((s) => s.setTab)
  const selection = useStore((s) => s.selection)
  const select = useStore((s) => s.select)
  const decide = useStore((s) => s.decide)
  const busy = useStore((s) => s.busy)

  const pending = snap.tasks.filter((t) => t.state === 'pending_review')
  const tasks = snap.tasks.filter((t) => t.state !== 'pending_review')
  const audit = snap.audit.filter((a) => a.action !== 'route').slice().reverse()

  return (
    <div className="card panel">
      <div className="tabs">
        <button className={`tab${tab === 'queue' ? ' on' : ''}`} onClick={() => setTab('queue')}>
          Review queue <span className="count">{pending.length}</span>
        </button>
        <button className={`tab${tab === 'tasks' ? ' on' : ''}`} onClick={() => setTab('tasks')}>
          Tasks <span className="count">{tasks.length}</span>
        </button>
        <button className={`tab${tab === 'requests' ? ' on' : ''}`} onClick={() => setTab('requests')}>
          Replenishment <span className="count">{snap.requests.length}</span>
        </button>
        <button className={`tab${tab === 'audit' ? ' on' : ''}`} onClick={() => setTab('audit')}>
          Audit <span className="count">{audit.length}</span>
        </button>
      </div>
      <div className="panel-body">
        {tab === 'queue' &&
          (pending.length === 0 ? (
            <div className="empty">Nothing waiting. Findings that rest on weak evidence (no gap detected, a missing box) stop here before a task is issued.</div>
          ) : (
            pending.map((t) => (
              <div key={t.task_id} className={`row queue${selection?.kind === 'task' && selection.id === t.task_id ? ' on' : ''}`} onClick={() => select({ kind: 'task', id: t.task_id })}>
                <span className="id">{t.task_id}</span>
                <span>
                  {TASK_LABEL[t.type]} {t.sku} <span className="dim">· {t.slot_id} · {STATUS_LABEL[t.finding].toLowerCase()}</span>
                </span>
                <span className="dim">conf {t.confidence.toFixed(2)}</span>
                <span style={{ display: 'flex', gap: 4 }}>
                  <button className="btn sm approve" disabled={busy} onClick={(e) => { e.stopPropagation(); void decide(t.task_id, true) }}>
                    Approve
                  </button>
                  <button className="btn sm reject" disabled={busy} onClick={(e) => { e.stopPropagation(); void decide(t.task_id, false) }}>
                    Reject
                  </button>
                </span>
              </div>
            ))
          ))}
        {tab === 'tasks' &&
          (tasks.length === 0 ? (
            <div className="empty">No tasks yet. Step the clock: a fault has to persist three unoccluded frames before it becomes a task.</div>
          ) : (
            tasks.map((t) => (
              <div key={t.task_id} className={`row${selection?.kind === 'task' && selection.id === t.task_id ? ' on' : ''}`} onClick={() => select({ kind: 'task', id: t.task_id })}>
                <span className="id">{t.task_id}</span>
                <span>
                  {TASK_LABEL[t.type]} {t.sku} <span className="dim">· {t.slot_id} · fr {t.frame}</span>
                </span>
                <span className="dim">priority {t.priority}</span>
                <span className={`pill ${t.state}`}>{t.source ? t.source : TASK_STATE_LABEL[t.state]}</span>
              </div>
            ))
          ))}
        {tab === 'requests' &&
          (snap.requests.length === 0 ? (
            <div className="empty">No replenishment requests: every restock so far was covered by the backroom or the DC.</div>
          ) : (
            snap.requests.map((r) => (
              <div key={r.po_id} className="row" onClick={() => select({ kind: 'task', id: r.task_id })}>
                <span className="id">{r.po_id}</span>
                <span>
                  {r.qty} x {r.sku} <span className="dim">· {r.family} · lead {r.lead_time_weeks} wk</span>
                </span>
                <span className="dim">{money(r.value)}</span>
                <span className="pill pending">{r.status}</span>
              </div>
            ))
          ))}
        {tab === 'audit' && audit.slice(0, 150).map((a, i) => <AuditRowView key={i} a={a} onPick={select} />)}
      </div>
    </div>
  )
}
