import { num, pct, useStore } from '../store'
import { STATUS_COLORS, STATUS_LABEL, STATUS_ORDER, TASK_LABEL } from '../layout'
import type { KpiId, TaskType } from '../types'

export function KpiCards() {
  const k = useStore((s) => s.snap!.kpis)
  const selection = useStore((s) => s.selection)
  const select = useStore((s) => s.select)
  const total = STATUS_ORDER.reduce((a, s) => a + (k.by_status[s] ?? 0), 0)
  const on = (id: KpiId) => (selection?.kind === 'kpi' && selection.id === id ? ' on' : '')
  const types = Object.entries(k.tasks_by_type) as [TaskType, number][]

  return (
    <div className="kpis">
      <div className={`card kpi good click${on('detector')}`} onClick={() => select({ kind: 'kpi', id: 'detector' })}>
        <div className="kpi-label">Detector mAP50 (held-out)</div>
        <div className="kpi-value">
          {k.map50 == null ? '-' : k.map50.toFixed(3)} <small>mAP50-95 {k.map50_95 == null ? '-' : k.map50_95.toFixed(3)}</small>
        </div>
        <div className="kpi-sub">
          {k.detector} · {k.train_seconds ? `${Math.round(k.train_seconds / 60)} min on CPU` : 'no training record'}
        </div>
      </div>
      <div className={`card kpi click${on('compliance')}`} onClick={() => select({ kind: 'kpi', id: 'compliance' })}>
        <div className="kpi-label">Planogram compliance</div>
        <div className="kpi-value">
          {pct(k.compliance)} <small>OSA {pct(k.osa)}</small>
        </div>
        <div className="status-bar">
          {STATUS_ORDER.map((s) => (
            <span key={s} style={{ width: `${((k.by_status[s] ?? 0) / Math.max(total, 1)) * 100}%`, background: STATUS_COLORS[s] }} />
          ))}
        </div>
        <div className="status-legend">
          {STATUS_ORDER.map((s) => (
            <span
              key={s}
              className={`legend-item${on(s)}`}
              onClick={(e) => {
                e.stopPropagation()
                select({ kind: 'kpi', id: s })
              }}
            >
              <i style={{ background: STATUS_COLORS[s] }} />
              {STATUS_LABEL[s]} {k.by_status[s] ?? 0}
            </span>
          ))}
        </div>
      </div>
      <div className="kpi-row">
        <div className={`card kpi bad click${on('gaps')}`} onClick={() => select({ kind: 'kpi', id: 'gaps' })}>
          <div className="kpi-label">Gaps</div>
          <div className="kpi-value">{k.gaps}</div>
          <div className="kpi-sub">empty slots of {k.slots}</div>
        </div>
        <div className={`card kpi warn click${on('pending')}`} onClick={() => select({ kind: 'kpi', id: 'pending' })}>
          <div className="kpi-label">Needs review</div>
          <div className="kpi-value">{k.pending_reviews}</div>
          <div className="kpi-sub">weak evidence</div>
        </div>
      </div>
      <div className={`card kpi click${on('tasks')}`} onClick={() => select({ kind: 'kpi', id: 'tasks' })}>
        <div className="kpi-label">Store tasks</div>
        <div className="kpi-value">
          {k.tasks_total} <small>{k.tasks_by_state.issued ?? 0} issued</small>
        </div>
        <div className="kpi-sub">{types.length ? types.map(([t, n]) => `${n} ${TASK_LABEL[t].toLowerCase()}`).join(' · ') : 'none yet'}</div>
      </div>
      <div className="kpi-row">
        <div className={`card kpi good click${on('alerts')}`} onClick={() => select({ kind: 'kpi', id: 'alerts' })}>
          <div className="kpi-label">False alerts</div>
          <div className="kpi-value">
            {pct(k.false_alert_rate, 1)} <small>raw {pct(k.false_alert_rate_raw, 1)}</small>
          </div>
          <div className="kpi-sub">
            time-to-detect {num(k.time_to_detect, 1)} fr <small>(raw {num(k.time_to_detect_raw, 1)})</small>
          </div>
        </div>
        <div className={`card kpi click${on('requests')}`} onClick={() => select({ kind: 'kpi', id: 'requests' })}>
          <div className="kpi-label">Replenish</div>
          <div className="kpi-value">{k.replenishment_requests}</div>
          <div className="kpi-sub">requests to supply planning</div>
        </div>
      </div>
    </div>
  )
}
