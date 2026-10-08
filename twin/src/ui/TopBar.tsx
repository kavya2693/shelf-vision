import { useEffect, useRef } from 'react'
import { useStore } from '../store'

export function TopBar() {
  const snap = useStore((s) => s.snap)
  const search = useStore((s) => s.search)
  const setSearch = useStore((s) => s.setSearch)
  const select = useStore((s) => s.select)
  const busy = useStore((s) => s.busy)
  const colour = useStore((s) => s.colour)
  const setColour = useStore((s) => s.setColour)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement !== input.current) {
        e.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = () => {
    if (!snap) return
    const q = search.trim().toUpperCase()
    if (!q) return
    const task = snap.tasks.find((t) => t.task_id === q)
    if (task) return select({ kind: 'task', id: task.task_id })
    const cam = snap.cameras.find((c) => c.camera_id === q)
    if (cam) return select({ kind: 'camera', id: cam.camera_id })
    const slot = snap.slots.find((s) => s.slot_id === q)
    if (slot) return select({ kind: 'slot', id: slot.slot_id })
    const bySku = snap.slots.find((s) => s.sku === q)
    if (bySku) return select({ kind: 'slot', id: bySku.slot_id })
    const bay = snap.bays.find((b) => b.bay_id === q)
    if (bay) return select({ kind: 'bay', id: bay.bay_id })
  }

  return (
    <div className="card topbar">
      <div className="logo">
        <div className="logo-mark">S</div>
        Shelf Vision <span className="logo-sub">store twin</span>
      </div>
      <div className="search">
        <span>&#9906;</span>
        <input ref={input} value={search} placeholder="Camera, slot, SKU, bay or task id" onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} />
        <kbd>/</kbd>
      </div>
      <div className="seg">
        <button className={`seg-btn${colour === 'status' ? ' on' : ''}`} onClick={() => setColour('status')}>
          Colour by status
        </button>
        <button className={`seg-btn${colour === 'product' ? ' on' : ''}`} onClick={() => setColour('product')}>
          By product
        </button>
      </div>
      <div className="site-select">
        {snap?.store ?? 'Store'} <span className="chev">&#9660;</span>
      </div>
      <div className="spacer" />
      {snap && (
        <span className="cycle-tag">
          Frame {snap.frame + 1} of {snap.frames} · {snap.cameras.length} cameras · {snap.slots.length} slots · detector {snap.detector}
        </span>
      )}
      <div className={`live${snap?.done ? ' off' : ''}`}>
        <span className="live-dot" /> {busy ? 'Working' : snap?.done ? 'Sequence end' : 'Live'}
      </div>
      <div className="avatar">SM</div>
    </div>
  )
}
