import { useEffect } from 'react'
import { useStore } from './store'
import { World } from './world/World'
import { TopBar } from './ui/TopBar'
import { KpiCards } from './ui/KpiCards'
import { TracePanel } from './ui/TracePanel'
import { Clock } from './ui/Clock'
import { BottomTabs } from './ui/BottomTabs'
import { ErrorBoundary } from './ui/ErrorBoundary'

const PLAY_MS = 2500

export function App() {
  const snap = useStore((s) => s.snap)
  const error = useStore((s) => s.error)
  const toast = useStore((s) => s.toast)
  const playing = useStore((s) => s.playing)
  const init = useStore((s) => s.init)
  const step = useStore((s) => s.step)
  const notify = useStore((s) => s.notify)

  useEffect(() => {
    void init()
  }, [init])

  useEffect(() => {
    if (!playing) return
    const t = setInterval(() => void step(1), PLAY_MS)
    return () => clearInterval(t)
  }, [playing, step])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => notify(null), 5000)
    return () => clearTimeout(t)
  }, [toast, notify])

  return (
    <div className="app">
      {snap && (
        <ErrorBoundary>
          <World />
        </ErrorBoundary>
      )}
      <div className="overlay">
        <TopBar />
        {snap && (
          <>
            <KpiCards />
            <TracePanel />
            <Clock />
            <BottomTabs />
            <div className="hint">Drag to pan, right-drag to orbit, scroll to zoom. Click a camera, a shelf slot, a pallet or an agent station.</div>
          </>
        )}
        {!snap && !error && <div className="loading">Connecting to the twin...</div>}
        {!snap && error && <div className="loading">Could not load the twin: {error}. Start it with `uv run shelf-vision-api`.</div>}
        {toast && <div className="toast">{toast}</div>}
        {snap && error && <div className="toast error">{error}</div>}
      </div>
    </div>
  )
}
