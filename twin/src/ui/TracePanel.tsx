import { frameSrc } from '../api'
import { money, pct, useStore } from '../store'
import { AGENTS, STATUS_COLORS, STATUS_LABEL, STATUS_ORDER, TASK_LABEL, TASK_STATE_LABEL } from '../layout'
import type { AuditRow, CameraTrace, KpiId, Selection, SlotStatus, SlotTrace, Task, TaskTrace } from '../types'
import { AuditRowView } from './BottomTabs'

function Pill({ s }: { s: string }) {
  return <span className={`pill ${s}`}>{(STATUS_LABEL as Record<string, string>)[s] ?? (TASK_STATE_LABEL as Record<string, string>)[s] ?? s.replace('_', ' ')}</span>
}

function Frame({ url, bust, caption }: { url: string; bust: number; caption: string }) {
  return (
    <div className="frame">
      <img src={frameSrc(url, bust)} alt={caption} />
      <div className="frame-cap">{caption}</div>
    </div>
  )
}

function TaskRows({ tasks, select }: { tasks: Task[]; select: (s: Selection) => void }) {
  if (!tasks.length) return <div className="blurb">No task on this slot.</div>
  return (
    <table className="mini-table">
      <tbody>
        {tasks.map((t) => (
          <tr key={t.task_id} className="link" onClick={() => select({ kind: 'task', id: t.task_id })}>
            <td>{t.task_id}</td>
            <td>{TASK_LABEL[t.type]}</td>
            <td>
              <Pill s={t.state} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Timeline({ rows, threshold }: { rows: SlotTrace['timeline']; threshold: number }) {
  return (
    <div className="timeline">
      {rows.map((r) => (
        <span
          key={r.frame}
          className={`tl${r.occluded >= threshold ? ' occ' : ''}`}
          style={{ background: STATUS_COLORS[r.raw] }}
          title={`frame ${r.frame}: ${STATUS_LABEL[r.raw]}${r.occluded >= threshold ? ' (hidden by shopper)' : ''} conf ${r.confidence.toFixed(2)}`}
        />
      ))}
    </div>
  )
}

function CameraView({ d, bust }: { d: CameraTrace; bust: number }) {
  const select = useStore((s) => s.select)
  const counts = Object.entries(d.by_class).sort((a, b) => b[1] - a[1])
  return (
    <>
      <Frame url={d.frame_url} bust={bust} caption={`${d.camera.camera_id} frame ${d.frame}: ${d.detections.length} detections (green products, red gaps, blue tags, grey shoppers)`} />
      <dl className="kv">
        <dt>Bay</dt>
        <dd className="link" onClick={() => select({ kind: 'bay', id: d.bay.bay_id })}>
          {d.bay.bay_id} · aisle {d.bay.aisle} {d.bay.side === 'L' ? 'left' : 'right'}
        </dd>
        <dt>Families</dt>
        <dd>{d.bay.families.join(', ')}</dd>
        <dt>Compliance</dt>
        <dd>
          {pct(d.compliance.compliance, 0)} · OSA {pct(d.compliance.osa, 0)}
        </dd>
      </dl>
      <div className="section">Detections by class</div>
      <div className="chips">
        {counts.map(([c, n]) => (
          <span key={c} className="chip">
            {c.replace('_', ' ')} <b>{n}</b>
          </span>
        ))}
      </div>
      <div className="section">Slots in view</div>
      <div className="slot-grid">
        {d.slots.map((s) => (
          <span key={s.slot_id} className="slot-cell link" style={{ background: STATUS_COLORS[s.status] }} title={`${s.slot_id}: ${STATUS_LABEL[s.status]}`} onClick={() => select({ kind: 'slot', id: s.slot_id })}>
            {s.slot_id.split('-').slice(1).join('-')}
          </span>
        ))}
      </div>
      {d.events.length > 0 && (
        <>
          <div className="section">Injected faults (synthetic ground truth)</div>
          <table className="mini-table">
            <tbody>
              {d.events
                .slice()
                .sort((a, b) => a.frame - b.frame)
                .map((e) => (
                  <tr key={e.slot_id} className="link" onClick={() => select({ kind: 'slot', id: e.slot_id })}>
                    <td>frame {e.frame}</td>
                    <td>{e.slot_id}</td>
                    <td>{STATUS_LABEL[e.fault]}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      )}
      <div className="section">Tasks from this camera</div>
      <TaskRows tasks={d.tasks} select={select} />
      <div className="section">Agent decisions</div>
      <div className="feed small">
        {d.audit
          .slice()
          .reverse()
          .slice(0, 12)
          .map((a, i) => (
            <AuditRowView key={i} a={a} onPick={select} />
          ))}
      </div>
    </>
  )
}

function SlotView({ d, bust }: { d: SlotTrace; bust: number }) {
  const select = useStore((s) => s.select)
  const det = d.detected
  const weak = (d.confidence ?? 1) < d.review_threshold
  return (
    <>
      <Frame url={d.frame_url} bust={bust} caption={`${d.slot.camera_id} frame ${d.frame}, slot ${d.slot.slot_id} outlined in orange`} />
      <div className="section">Planogram vs detected</div>
      <table className="mini-table compare">
        <thead>
          <tr>
            <th></th>
            <th>Planned</th>
            <th>Seen</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>SKU</td>
            <td>{d.planogram.sku}</td>
            <td>{det ? (det.foreign ? `${det.foreign} foreign (${det.foreign_family})` : det.facings_found ? d.planogram.sku : 'nothing') : '-'}</td>
          </tr>
          <tr>
            <td>Family</td>
            <td>{d.planogram.family}</td>
            <td>{det?.foreign_family ?? d.planogram.family}</td>
          </tr>
          <tr>
            <td>Facings</td>
            <td>{d.planogram.facings}</td>
            <td>{det ? det.facings_found : '-'}</td>
          </tr>
          <tr>
            <td>Gap</td>
            <td>none</td>
            <td>{det ? `${Math.round(det.gap_fraction * 100)}% of slot` : '-'}</td>
          </tr>
          <tr>
            <td>Price tag</td>
            <td>{d.planogram.price.toFixed(2)}</td>
            <td>{det ? (det.tag_seen ? 'seen' : 'not seen') : '-'}</td>
          </tr>
          <tr>
            <td>Hidden</td>
            <td>-</td>
            <td>{det ? `${Math.round(det.occluded * 100)}% by shoppers` : '-'}</td>
          </tr>
        </tbody>
      </table>
      <dl className="kv">
        <dt>This frame</dt>
        <dd>{det ? <Pill s={det.raw_status} /> : '-'}</dd>
        <dt>Confirmed</dt>
        <dd>
          <Pill s={d.status} />
        </dd>
        <dt>Evidence</dt>
        <dd>
          {d.confidence == null ? '-' : d.confidence.toFixed(2)}
          {weak ? ' · below review threshold' : ''}
        </dd>
        {d.tracker && (
          <>
            <dt>Streak</dt>
            <dd>
              {d.tracker.streak} frame{d.tracker.streak === 1 ? '' : 's'} of {STATUS_LABEL[d.tracker.candidate].toLowerCase()}
              {d.tracker.confirmed_frame >= 0 ? ` · confirmed fr ${d.tracker.confirmed_frame}` : ''}
            </dd>
          </>
        )}
        {d.truth && (
          <>
            <dt>Ground truth</dt>
            <dd>
              <Pill s={d.truth} /> {d.truth === d.status ? '' : '(disagrees)'}
            </dd>
          </>
        )}
        <dt>Velocity</dt>
        <dd>{d.velocity} units/wk</dd>
        <dt>Stock</dt>
        <dd>{d.stock ? `${d.stock.backroom} backroom · ${d.stock.dc} DC` : '-'}</dd>
      </dl>
      <div className="section">Raw status per frame (hatched = hidden by a shopper)</div>
      <Timeline rows={d.timeline} threshold={0.35} />
      <div className="section">Tasks</div>
      <TaskRows tasks={d.tasks} select={select} />
      {d.requests.length > 0 && (
        <>
          <div className="section">Replenishment</div>
          {d.requests.map((r) => (
            <div key={r.po_id} className="blurb">
              {r.po_id}: {r.qty} x {r.sku}, {money(r.value)}, lead {r.lead_time_weeks} wk
            </div>
          ))}
        </>
      )}
      <div className="section">Agent decisions on this slot</div>
      <div className="feed small">
        {d.audit
          .slice()
          .reverse()
          .slice(0, 10)
          .map((a, i) => (
            <AuditRowView key={i} a={a} onPick={select} />
          ))}
      </div>
    </>
  )
}

function TaskView({ d, bust }: { d: TaskTrace; bust: number }) {
  const select = useStore((s) => s.select)
  const decide = useStore((s) => s.decide)
  const busy = useStore((s) => s.busy)
  const t = d.task
  return (
    <>
      <div className="journey">
        {d.steps.map((s, i) => (
          <div key={s.name} className={`jstep${s.done ? ' done' : ''}`}>
            <div className="jdot">{s.done ? '✓' : i + 1}</div>
            <div className="jname">{s.name}</div>
            <div className="jdetail">{s.detail}</div>
          </div>
        ))}
      </div>
      <p className="blurb instruction">{t.instruction}</p>
      {t.state === 'pending_review' && (
        <div className="btn-row">
          <button className="btn approve" disabled={busy} onClick={() => void decide(t.task_id, true)}>
            Approve and issue
          </button>
          <button className="btn reject" disabled={busy} onClick={() => void decide(t.task_id, false)}>
            Reject
          </button>
        </div>
      )}
      <Frame url={d.frame_url} bust={bust} caption={`${t.camera_id} frame ${t.frame}: the evidence, slot ${t.slot_id} outlined`} />
      <dl className="kv">
        <dt>Finding</dt>
        <dd>
          <Pill s={t.finding} /> conf {t.confidence.toFixed(2)}
        </dd>
        <dt>Slot</dt>
        <dd className="link" onClick={() => select({ kind: 'slot', id: t.slot_id })}>
          {t.slot_id}
        </dd>
        <dt>Camera</dt>
        <dd className="link" onClick={() => select({ kind: 'camera', id: t.camera_id })}>
          {t.camera_id}
        </dd>
        <dt>SKU</dt>
        <dd>
          {t.sku} · {t.family}
        </dd>
        <dt>Priority</dt>
        <dd>{t.priority} (family velocity x task weight)</dd>
        {t.qty > 0 && (
          <>
            <dt>Quantity</dt>
            <dd>{t.qty} units</dd>
          </>
        )}
        {t.source && (
          <>
            <dt>Source</dt>
            <dd>{t.source === 'replenishment' ? `replenishment ${t.request_id}` : t.source}</dd>
          </>
        )}
        <dt>Stock now</dt>
        <dd>{d.stock ? `${d.stock.backroom} backroom · ${d.stock.dc} DC` : '-'}</dd>
      </dl>
      {d.request && (
        <>
          <div className="section">Replenishment request (supply-planning PO format)</div>
          <dl className="kv">
            <dt>PO id</dt>
            <dd>{d.request.po_id}</dd>
            <dt>Quantity</dt>
            <dd>
              {d.request.qty} (MOQ {d.request.moq})
            </dd>
            <dt>Value</dt>
            <dd>{money(d.request.value)}</dd>
            <dt>Lead time</dt>
            <dd>{d.request.lead_time_weeks} weeks</dd>
            <dt>Status</dt>
            <dd>
              <Pill s={d.request.status} />
            </dd>
          </dl>
        </>
      )}
      <div className="section">Trace</div>
      <div className="feed small">
        {d.audit
          .slice()
          .reverse()
          .slice(0, 12)
          .map((a, i) => (
            <AuditRowView key={i} a={a} onPick={select} />
          ))}
      </div>
    </>
  )
}

function BayView({ id }: { id: string }) {
  const snap = useStore((s) => s.snap!)
  const select = useStore((s) => s.select)
  const bay = snap.bays.find((b) => b.bay_id === id)
  const slots = snap.slots.filter((s) => s.bay_id === id)
  const k = snap.kpis.by_bay?.[id]
  if (!bay) return null
  return (
    <>
      <dl className="kv">
        <dt>Camera</dt>
        <dd className="link" onClick={() => select({ kind: 'camera', id: bay.camera_id })}>
          {bay.camera_id}
        </dd>
        <dt>Families</dt>
        <dd>{bay.families.join(', ')}</dd>
        <dt>Compliance</dt>
        <dd>{k ? `${pct(k.compliance, 0)} · OSA ${pct(k.osa, 0)}` : '-'}</dd>
      </dl>
      <div className="section">Slots (shelf-index)</div>
      <table className="mini-table">
        <tbody>
          {slots.map((s) => (
            <tr key={s.slot_id} className="link" onClick={() => select({ kind: 'slot', id: s.slot_id })}>
              <td>
                S{s.shelf}-{s.index}
              </td>
              <td>
                {s.sku} x{s.facings}
              </td>
              <td>
                <Pill s={s.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function AgentView({ id }: { id: string }) {
  const snap = useStore((s) => s.snap!)
  const select = useStore((s) => s.select)
  const a = AGENTS.find((x) => x.id === id)
  const rows = snap.audit.filter((r) => r.agent === id && r.action !== 'route').slice().reverse()
  const blurb: Record<string, string> = {
    vision_agent: 'Runs the YOLOv8n detector on the latest frame of every camera and hands the boxes on. It never decides anything about the shelf.',
    compliance_agent: 'Maps each box through the camera homography onto the bay plane, assigns it to a planogram slot, derives the raw status, and confirms it only after three consecutive unoccluded frames agree.',
    merchandising_agent: 'Turns confirmed findings into store tasks (restock, relocate, re-face, fix tag), prioritised by family velocity, and pauses the graph for a reviewer when the evidence is weak.',
    inventory_agent: 'Reserves backroom stock for restocks, falls back to a DC transfer, and raises a replenishment request in the supply-planning PO format when neither holds the SKU.',
    human_reviewer: 'The person who approves or rejects weak-evidence findings from the review queue.',
    supervisor: 'Routes work between the agents in a fixed order each frame.',
  }
  return (
    <>
      <p className="blurb">{blurb[id]}</p>
      {a && (
        <dl className="kv">
          <dt>Method</dt>
          <dd>{a.sub}</dd>
          <dt>Entries</dt>
          <dd>{rows.length}</dd>
        </dl>
      )}
      <div className="section">Latest decisions</div>
      <div className="feed small">
        {rows.slice(0, 25).map((r: AuditRow, i) => (
          <AuditRowView key={i} a={r} onPick={select} />
        ))}
      </div>
    </>
  )
}

function KpiView({ id }: { id: KpiId }) {
  const snap = useStore((s) => s.snap!)
  const select = useStore((s) => s.select)
  const k = snap.kpis
  if (STATUS_ORDER.includes(id as SlotStatus)) {
    const rows = snap.slots.filter((s) => s.status === id)
    return (
      <>
        <p className="blurb">
          {rows.length} slot{rows.length === 1 ? '' : 's'} currently {STATUS_LABEL[id as SlotStatus].toLowerCase()}.
        </p>
        <table className="mini-table">
          <tbody>
            {rows.slice(0, 60).map((s) => (
              <tr key={s.slot_id} className="link" onClick={() => select({ kind: 'slot', id: s.slot_id })}>
                <td>{s.slot_id}</td>
                <td>{s.sku}</td>
                <td>{s.task_id ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>
    )
  }
  const text: Record<string, string> = {
    detector: `YOLOv8n fine-tuned on ${k.detector === 'oracle' ? 'nothing: the twin is replaying ground-truth boxes' : 'synthetic shelf frames'}; mAP50 is measured on a held-out synthetic test split, not on real CCTV. The gap class is the weakest.`,
    compliance: 'Planogram compliance is the share of slots exactly as planned. On-shelf availability counts a slot as available if the planned product is present at all, so a short-faced or untagged slot still counts.',
    osa: 'On-shelf availability: slots where the planned SKU is present.',
    gaps: 'Slots confirmed empty: the restock queue for the floor team.',
    tasks: 'Every task links back to the camera, frame and slot that caused it. Priority is family sales velocity times a task weight.',
    pending: 'Findings whose evidence is weaker than the review threshold wait for a person before a task is issued.',
    alerts: 'Measured on the deployment sequences against ground truth: an alert on a slot that is actually fine is a false alert. Smoothing removes the ones caused by shoppers standing in front of the shelf, at the cost of about two frames of latency.',
    requests: 'Restocks the backroom and the DC cannot cover become replenishment requests in the supply-planning purchase-order format.',
  }
  return (
    <>
      <p className="blurb">{text[id]}</p>
      {id === 'alerts' && (
        <dl className="kv">
          <dt>False alerts raw</dt>
          <dd>{pct(k.false_alert_rate_raw, 1)}</dd>
          <dt>False alerts smoothed</dt>
          <dd>{pct(k.false_alert_rate, 1)}</dd>
          <dt>Time-to-detect raw</dt>
          <dd>{k.time_to_detect_raw ?? '-'} frames</dd>
          <dt>Time-to-detect smoothed</dt>
          <dd>{k.time_to_detect ?? '-'} frames</dd>
          <dt>Status accuracy</dt>
          <dd>{pct(k.status_accuracy, 1)}</dd>
        </dl>
      )}
      {id === 'requests' && (
        <table className="mini-table">
          <tbody>
            {snap.requests.map((r) => (
              <tr key={r.po_id} className="link" onClick={() => select({ kind: 'task', id: r.task_id })}>
                <td>{r.po_id}</td>
                <td>
                  {r.qty} x {r.sku}
                </td>
                <td>{money(r.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(id === 'tasks' || id === 'pending' || id === 'gaps') && (
        <table className="mini-table">
          <tbody>
            {snap.tasks
              .filter((t) => (id === 'pending' ? t.state === 'pending_review' : id === 'gaps' ? t.type === 'restock' : true))
              .slice(0, 60)
              .map((t) => (
                <tr key={t.task_id} className="link" onClick={() => select({ kind: 'task', id: t.task_id })}>
                  <td>{t.task_id}</td>
                  <td>
                    {TASK_LABEL[t.type]} {t.slot_id}
                  </td>
                  <td>
                    <Pill s={t.state} />
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function BackroomView({ id }: { id: string }) {
  const snap = useStore((s) => s.snap!)
  const select = useStore((s) => s.select)
  const skus = [...new Map(snap.slots.filter((s) => s.family === id).map((s) => [s.sku, s])).values()]
  return (
    <>
      <p className="blurb">Backroom and DC stock for {id}. Restock tasks draw from here; SKUs with nothing anywhere become replenishment requests.</p>
      <table className="mini-table">
        <thead>
          <tr>
            <th>SKU</th>
            <th>Backroom</th>
            <th>DC</th>
          </tr>
        </thead>
        <tbody>
          {skus.map((s) => (
            <tr key={s.sku} className="link" onClick={() => select({ kind: 'slot', id: s.slot_id })}>
              <td>{s.sku}</td>
              <td>{snap.stock[s.sku]?.backroom ?? 0}</td>
              <td>{snap.stock[s.sku]?.dc ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export function TracePanel() {
  const selection = useStore((s) => s.selection)
  const trace = useStore((s) => s.trace)
  const traceKey = useStore((s) => s.traceKey)
  const select = useStore((s) => s.select)
  const back = useStore((s) => s.back)
  const history = useStore((s) => s.history)
  const frame = useStore((s) => s.snap?.frame ?? 0)
  if (!selection) return null
  const kinds: Record<string, string> = { camera: 'CCTV camera', slot: 'Shelf slot', task: 'Store task', bay: 'Shelf bay', agent: 'Agent', kpi: 'KPI', backroom: 'Backroom stock' }
  const loading = (selection.kind === 'camera' || selection.kind === 'slot' || selection.kind === 'task') && (!trace || traceKey !== `${selection.kind}:${selection.id}`)
  const title = selection.kind === 'agent' ? (AGENTS.find((a) => a.id === selection.id)?.label ?? selection.id) + ' agent' : selection.kind === 'kpi' ? String(selection.id).replace('_', ' ') : String(selection.id)
  return (
    <div className="card detail">
      <div className="detail-head">
        {history.length > 0 && (
          <button className="detail-close" title="Back" onClick={back}>
            &#8592;
          </button>
        )}
        <div>
          <div className="detail-kind">{kinds[selection.kind]}</div>
          <div className="detail-title">{title}</div>
        </div>
        <button className="detail-close" onClick={() => select(null)}>
          &#10005;
        </button>
      </div>
      <div className="detail-body">
        {loading && <div className="blurb">Loading trace...</div>}
        {!loading && trace?.kind === 'camera' && <CameraView d={trace.data} bust={frame} />}
        {!loading && trace?.kind === 'slot' && <SlotView d={trace.data} bust={frame} />}
        {!loading && trace?.kind === 'task' && <TaskView d={trace.data} bust={frame} />}
        {selection.kind === 'bay' && <BayView id={selection.id} />}
        {selection.kind === 'agent' && <AgentView id={selection.id} />}
        {selection.kind === 'kpi' && <KpiView id={selection.id} />}
        {selection.kind === 'backroom' && <BackroomView id={selection.id} />}
      </div>
    </div>
  )
}
