import { clock, useStore } from '../store'

export function Clock() {
  const snap = useStore((s) => s.snap!)
  const busy = useStore((s) => s.busy)
  const playing = useStore((s) => s.playing)
  const setPlaying = useStore((s) => s.setPlaying)
  const step = useStore((s) => s.step)
  const reset = useStore((s) => s.reset)
  const pct = ((snap.frame + 1) / snap.frames) * 100
  return (
    <div className="card clock">
      <div className="clock-week">
        <div className="clock-label">Camera clock</div>
        <div className="clock-value">{clock(snap.frame)}</div>
        <div className="clock-sub">
          frame {snap.frame + 1} of {snap.frames} · one frame every 30 s{snap.pending.length ? ` · ${snap.pending.length} awaiting review` : ''}
        </div>
        <div className="progress">
          <span style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="clock-buttons">
        <button className="btn primary" disabled={busy || playing || snap.done} onClick={() => void step(1)}>
          Next frame
        </button>
        <button className={`btn${playing ? ' danger' : ''}`} disabled={snap.done && !playing} onClick={() => setPlaying(!playing)}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <button className="btn" disabled={busy || playing || snap.done} onClick={() => void step(4)}>
          Skip 4
        </button>
        <button className="btn ghost" disabled={busy || playing} onClick={() => void reset()}>
          Reset
        </button>
      </div>
    </div>
  )
}
