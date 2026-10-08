import type { CameraTrace, SlotTrace, Snapshot, Task, TaskTrace } from './types'

/** Relative base so the Vite dev server and `vite preview` can proxy /api to :8020. */
export const BASE = './api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`)
  return (await res.json()) as T
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`)
  return (await res.json()) as T
}

export const api = {
  state: () => get<Snapshot>('/state?events=200'),
  step: (frames = 1) => post<{ state: Snapshot }>('/step', { frames }),
  decide: (task_id: string, approve: boolean) => post<{ task: Task; state: Snapshot }>('/decide', { task_id, approve }),
  reset: () => post<Snapshot>('/reset', {}),
  traceCamera: (id: string) => get<CameraTrace>(`/trace/camera/${id}`),
  traceSlot: (id: string) => get<SlotTrace>(`/trace/slot/${id}`),
  traceTask: (id: string) => get<TaskTrace>(`/trace/task/${id}`),
}

/** Frame URLs from the API are absolute (/api/...); rebase them onto the proxy prefix. */
export function frameSrc(url: string, bust: number): string {
  return `${BASE}${url.replace(/^\/api/, '')}${url.includes('?') ? '&' : '?'}v=${bust}`
}
