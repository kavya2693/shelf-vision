import { create } from 'zustand'
import { api } from './api'
import type { AgentId, CameraTrace, Selection, SlotTrace, Snapshot, TaskTrace } from './types'

export type Trace = { kind: 'camera'; data: CameraTrace } | { kind: 'slot'; data: SlotTrace } | { kind: 'task'; data: TaskTrace }
export type Tab = 'queue' | 'tasks' | 'requests' | 'audit'
export type ColourMode = 'status' | 'product'

interface State {
  snap: Snapshot | null
  error: string | null
  busy: boolean
  playing: boolean
  selection: Selection
  hover: Selection
  history: Selection[]
  trace: Trace | null
  traceKey: string | null
  tab: Tab
  colour: ColourMode
  search: string
  toast: string | null
  activeAgent: AgentId | null

  init: () => Promise<void>
  step: (frames?: number) => Promise<void>
  decide: (taskId: string, ok: boolean) => Promise<void>
  reset: () => Promise<void>
  setPlaying: (p: boolean) => void
  select: (s: Selection, push?: boolean) => void
  back: () => void
  setHover: (h: Selection) => void
  setTab: (t: Tab) => void
  setColour: (c: ColourMode) => void
  setSearch: (s: string) => void
  notify: (t: string | null) => void
}

function key(s: Selection): string | null {
  return s ? `${s.kind}:${String(s.id)}` : null
}

export const useStore = create<State>((set, get) => {
  async function run(label: string, fn: () => Promise<Snapshot>) {
    if (get().busy) return
    set({ busy: true, error: null })
    try {
      const snap = await fn()
      set({ snap, busy: false })
      void refreshTrace()
    } catch (e) {
      set({ busy: false, error: `${label}: ${(e as Error).message}`, playing: false })
    }
  }

  async function refreshTrace() {
    const { selection } = get()
    if (!selection) return
    const k = key(selection)
    try {
      let trace: Trace | null = null
      if (selection.kind === 'camera') trace = { kind: 'camera', data: await api.traceCamera(selection.id) }
      else if (selection.kind === 'slot') trace = { kind: 'slot', data: await api.traceSlot(selection.id) }
      else if (selection.kind === 'task') trace = { kind: 'task', data: await api.traceTask(selection.id) }
      if (key(get().selection) === k) set({ trace, traceKey: k })
    } catch (e) {
      if (key(get().selection) === k) set({ trace: null, traceKey: k, error: (e as Error).message })
    }
  }

  // The agent stations light up as the audit feed grows, so a step reads as work moving
  // through the control room.
  function animateAgents(snap: Snapshot) {
    const order: AgentId[] = ['vision_agent', 'compliance_agent', 'merchandising_agent', 'inventory_agent']
    const seen = order.filter((a) => snap.audit.some((r) => r.agent === a && r.frame === snap.frame))
    seen.forEach((a, i) => setTimeout(() => set({ activeAgent: a }), i * 350))
    setTimeout(() => set({ activeAgent: null }), seen.length * 350 + 600)
  }

  return {
    snap: null,
    error: null,
    busy: false,
    playing: false,
    selection: null,
    hover: null,
    history: [],
    trace: null,
    traceKey: null,
    tab: 'queue',
    colour: 'status',
    search: '',
    toast: null,
    activeAgent: null,

    init: async () => {
      set({ busy: true })
      try {
        const snap = await api.state()
        set({ snap, busy: false })
      } catch (e) {
        set({ busy: false, error: (e as Error).message })
      }
    },
    step: async (frames = 1) => {
      const before = get().snap
      if (before?.done) {
        set({ playing: false, toast: 'End of the recorded sequence. Reset to replay it.' })
        return
      }
      await run('step', async () => (await api.step(frames)).state)
      const snap = get().snap
      if (snap) {
        animateAgents(snap)
        const newTasks = snap.kpis.tasks_total - (before?.kpis.tasks_total ?? 0)
        if (newTasks > 0) set({ toast: `Frame ${snap.frame}: ${newTasks} new task${newTasks > 1 ? 's' : ''}${snap.kpis.pending_reviews ? `, ${snap.kpis.pending_reviews} waiting for review` : ''}` })
        if (snap.done) set({ playing: false })
      }
    },
    decide: async (taskId, ok) => {
      await run('decide', async () => (await api.decide(taskId, ok)).state)
      set({ toast: `${taskId} ${ok ? 'approved: task issued to the floor' : 'rejected'}` })
    },
    reset: async () => {
      await run('reset', () => api.reset())
      set({ selection: null, trace: null, traceKey: null, history: [], playing: false, toast: 'Twin reset to frame 0' })
    },
    setPlaying: (playing) => set({ playing }),
    select: (s, push = true) => {
      const cur = get().selection
      if (key(s) === key(cur)) return
      set({
        selection: s,
        history: push && cur ? [...get().history.slice(-20), cur] : get().history,
        trace: null,
        traceKey: key(s),
        tab: s?.kind === 'task' ? 'tasks' : get().tab,
      })
      void refreshTrace()
    },
    back: () => {
      const h = get().history
      if (!h.length) return
      const prev = h[h.length - 1]
      set({ history: h.slice(0, -1) })
      get().select(prev, false)
    },
    setHover: (hover) => set({ hover }),
    setTab: (tab) => set({ tab }),
    setColour: (colour) => set({ colour }),
    setSearch: (search) => set({ search }),
    notify: (toast) => set({ toast }),
  }
})

export const pct = (v: number | null | undefined, d = 1) => (v == null ? '-' : `${(v * 100).toFixed(d)}%`)
export const num = (v: number | null | undefined, d = 0) => (v == null ? '-' : v.toFixed(d))
export const money = (v: number | null | undefined) => (v == null ? '-' : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0))
export const clock = (frame: number) => {
  const s = frame * 30
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
