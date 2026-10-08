export type SlotStatus = 'ok' | 'out_of_stock' | 'misplaced' | 'wrong_facings' | 'missing_tag'
export type TaskType = 'restock' | 'relocate' | 'reface' | 'fix_tag'
export type TaskState = 'issued' | 'pending_review' | 'rejected'
export type AgentId = 'supervisor' | 'vision_agent' | 'compliance_agent' | 'merchandising_agent' | 'inventory_agent' | 'human_reviewer'

export interface Bay {
  bay_id: string
  aisle: number
  side: 'L' | 'R'
  families: string[]
  camera_id: string
}

export interface Camera {
  camera_id: string
  bay_id: string
  label: string
  boxes: number
  shoppers: number
  frame_url: string
}

export interface SlotRow {
  slot_id: string
  bay_id: string
  shelf: number
  index: number
  sku: string
  family: string
  short: string
  rgb: [number, number, number]
  facings: number
  pack_w: number
  pack_h: number
  status: SlotStatus
  confidence: number | null
  task_id: string | null
  task_state: TaskState | null
}

export interface Task {
  task_id: string
  type: TaskType
  slot_id: string
  bay_id: string
  camera_id: string
  frame: number
  sku: string
  family: string
  finding: SlotStatus
  confidence: number
  priority: number
  qty: number
  instruction: string
  review: 'auto' | 'pending' | 'approved' | 'rejected'
  state: TaskState
  source: 'backroom' | 'dc' | 'replenishment' | null
  request_id: string | null
}

export interface Replenishment {
  po_id: string
  sku: string
  family: string
  source: string
  status: string
  qty: number
  moq: number
  unit_cost: number
  value: number
  lead_time_weeks: number
  slot_id: string
  task_id: string
  camera_id: string
  frame: number
}

export interface AuditRow {
  ts: string
  agent: AgentId
  action: string
  frame?: number
  camera?: string
  slot?: string
  sku?: string
  task?: string
  request?: string
  to?: string
  boxes?: number
  compliance?: number
  osa?: number
  new_findings?: number
  faults?: Record<string, number>
  occluded?: number
  type?: string
  priority?: number
  review?: string
  confidence?: number
  approved?: boolean
  source?: string | null
  qty?: number
  value?: number
}

export interface Kpis {
  slots: number
  compliance: number
  osa: number
  gaps: number
  by_status: Record<SlotStatus, number>
  by_bay?: Record<string, { compliance: number; osa: number }>
  frame: number
  frames: number
  tasks_total: number
  tasks_by_type: Partial<Record<TaskType, number>>
  tasks_by_state: Partial<Record<TaskState, number>>
  pending_reviews: number
  replenishment_requests: number
  replenishment_value: number
  detector: string
  map50: number | null
  map50_95: number | null
  train_seconds: number | null
  false_alert_rate: number | null
  false_alert_rate_raw: number | null
  time_to_detect: number | null
  time_to_detect_raw: number | null
  status_accuracy: number | null
}

export interface Snapshot {
  store: string
  frame: number
  frames: number
  done: boolean
  detector: string
  bays: Bay[]
  cameras: Camera[]
  slots: SlotRow[]
  tasks: Task[]
  pending: { task_id: string; slot_id: string; finding: SlotStatus; confidence: number }[]
  requests: Replenishment[]
  stock: Record<string, { backroom: number; dc: number }>
  kpis: Kpis
  history: ({ frame: number } & Partial<Kpis>)[]
  audit: AuditRow[]
  briefing: string
}

export interface Detection {
  cls: string
  conf: number
  xyxy: [number, number, number, number]
}

export interface CameraTrace {
  camera: { camera_id: string; bay_id: string; label: string }
  bay: { bay_id: string; aisle: number; side: string; families: string[] }
  frame: number
  frame_url: string
  detections: Detection[]
  by_class: Record<string, number>
  slots: { slot_id: string; status: SlotStatus; confidence: number | null }[]
  compliance: { compliance: number; osa: number; gaps: number }
  tasks: Task[]
  audit: AuditRow[]
  events: { frame: number; slot_id: string; fault: SlotStatus }[]
}

export interface SlotTrace {
  slot: { slot_id: string; bay_id: string; shelf: number; index: number; camera_id: string }
  planogram: { sku: string; family: string; facings: number; price: number; tag: boolean }
  detected: {
    facings_found: number
    foreign: number
    foreign_family: string | null
    gap_fraction: number
    tag_seen: boolean
    occluded: number
    raw_status: SlotStatus
    confidence: number
  } | null
  status: SlotStatus
  confidence: number | null
  tracker: { confirmed: SlotStatus; candidate: SlotStatus; streak: number; confidence: number; confirmed_frame: number } | null
  review_threshold: number
  truth: SlotStatus | null
  frame: number
  frame_url: string
  detections: Detection[]
  timeline: { frame: number; raw: SlotStatus; confidence: number; occluded: number }[]
  tasks: Task[]
  requests: Replenishment[]
  stock: { backroom: number; dc: number } | null
  velocity: number
  audit: AuditRow[]
}

export interface TaskTrace {
  task: Task
  slot: SlotTrace['slot']
  planogram: SlotTrace['planogram']
  detected: SlotTrace['detected']
  status: SlotStatus
  stock: { backroom: number; dc: number } | null
  frame_url: string
  request: Replenishment | null
  audit: AuditRow[]
  steps: { name: string; done: boolean; detail: string }[]
}

export type KpiId = 'detector' | 'compliance' | 'osa' | 'gaps' | 'tasks' | 'pending' | 'alerts' | 'requests' | SlotStatus

export type Selection =
  | { kind: 'camera'; id: string }
  | { kind: 'slot'; id: string }
  | { kind: 'task'; id: string }
  | { kind: 'bay'; id: string }
  | { kind: 'agent'; id: AgentId }
  | { kind: 'kpi'; id: KpiId }
  | { kind: 'backroom'; id: string }
  | null
