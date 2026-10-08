import type { AgentId, SlotStatus, TaskState, TaskType } from './types'

/* One scene unit is 250 mm: a slot is one unit wide. ------------------------------------- */
export const MM = 1 / 250

export const COLORS = {
  ground: '#ebe8f7',
  floor: '#f4f2fb',
  floorLine: '#dedbee',
  wall: '#ffffff',
  wallShade: '#eef0ff',
  roof: '#dcdaf0',
  brand: '#3b5bff',
  brandSoft: '#9db0ff',
  shelf: '#d9d7ea',
  shelfBack: '#4a4e5c',
  shelfEdge: '#f7f6fc',
  tag: '#fffdf4',
  camera: '#2b2f45',
  cone: '#3b5bff',
  pallet: '#d4b48f',
  road: '#cfcbe3',
  tree: '#8fd3a8',
  treeDark: '#6fbf8c',
  trunk: '#c9a98a',
  hover: '#ff7a1a',
  selected: '#ff7a1a',
} as const

export const STATUS_COLORS: Record<SlotStatus, string> = {
  ok: '#39c17a',
  out_of_stock: '#ef4b4b',
  misplaced: '#f26b1d',
  wrong_facings: '#f5a623',
  missing_tag: '#3b82f6',
}
export const STATUS_LABEL: Record<SlotStatus, string> = {
  ok: 'As planned',
  out_of_stock: 'Out of stock',
  misplaced: 'Misplaced',
  wrong_facings: 'Short facings',
  missing_tag: 'Missing tag',
}
export const STATUS_ORDER: SlotStatus[] = ['out_of_stock', 'misplaced', 'wrong_facings', 'missing_tag', 'ok']

export const TASK_LABEL: Record<TaskType, string> = {
  restock: 'Restock',
  relocate: 'Relocate',
  reface: 'Re-face',
  fix_tag: 'Fix tag',
}
export const TASK_STATE_LABEL: Record<TaskState, string> = {
  issued: 'Issued',
  pending_review: 'Needs review',
  rejected: 'Rejected',
}

export const AGENTS: { id: AgentId; label: string; sub: string; x: number }[] = [
  { id: 'vision_agent', label: 'Vision', sub: 'YOLOv8n per camera', x: -10.5 },
  { id: 'compliance_agent', label: 'Compliance', sub: 'slot geometry + smoothing', x: -3.5 },
  { id: 'merchandising_agent', label: 'Merchandising', sub: 'tasks by velocity', x: 3.5 },
  { id: 'inventory_agent', label: 'Inventory', sub: 'backroom, DC, replenish', x: 10.5 },
]

/* Store geometry ------------------------------------------------------------------------- */
export const BAY = { width: 5, height: 3.84, depth: 1.6, shelves: 3, pitch: 1.28, board: 0.12 }
// Each aisle is one gondola run: its left and right bay stand side by side and face the
// walkway in front of them, so every shelf face is visible from the default view.
export const AISLE_Z = [-11, -1.5, 8]
export const BAY_X = { L: -3.1, R: 3.1 }
export const STORE = { width: 52, depth: 38, wallHeight: 5.5 }
export const BACKROOM = { x: 0, z: -22, width: 30, depth: 10 }
export const CONTROL_Z = 15
export const CAMERA_Y = 4.6
export const CAMERA_DZ = 4.8

export function bayTransform(aisle: number, side: 'L' | 'R'): { x: number; z: number; rotation: number } {
  return { x: BAY_X[side], z: AISLE_Z[aisle - 1] - 1.8, rotation: 0 }
}

export function cameraPosition(aisle: number, side: 'L' | 'R'): [number, number, number] {
  // Mounted high at the far end of the run, looking back along it at the bay.
  return [BAY_X[side] + (side === 'L' ? -3.4 : 3.4), CAMERA_Y, AISLE_Z[aisle - 1] + CAMERA_DZ]
}

/** Top of the shelf board for shelf s (0 = top), in bay-local units. */
export function boardY(shelf: number): number {
  return BAY.height - (shelf + 1) * BAY.pitch + BAY.board
}
