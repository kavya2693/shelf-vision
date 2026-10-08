import { useMemo } from 'react'
import { useStore } from '../store'
import { AGENTS, BACKROOM, COLORS, CONTROL_Z } from '../layout'
import { Label, Pick } from './Pick'

const rgb = (c: [number, number, number]) => `rgb(${c[0]},${c[1]},${c[2]})`

/** Backroom pallets: one stack per family, height proportional to units on hand. */
export function Backroom() {
  const stock = useStore((s) => s.snap?.stock ?? {})
  const slots = useStore((s) => s.snap?.slots ?? [])
  const requests = useStore((s) => s.snap?.requests ?? [])
  const select = useStore((s) => s.select)
  const families = useMemo(() => {
    const m = new Map<string, { units: number; dc: number; colour: string; skus: Set<string> }>()
    for (const s of slots) {
      const f = m.get(s.family) ?? { units: 0, dc: 0, colour: rgb(s.rgb), skus: new Set<string>() }
      if (!f.skus.has(s.sku)) {
        f.skus.add(s.sku)
        f.units += stock[s.sku]?.backroom ?? 0
        f.dc += stock[s.sku]?.dc ?? 0
      }
      m.set(s.family, f)
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [slots, stock])
  const total = families.reduce((a, [, f]) => a + f.units, 0)
  return (
    <group>
      {families.map(([name, f], i) => {
        const x = BACKROOM.x - BACKROOM.width / 2 + 3 + i * 3
        const layers = Math.max(1, Math.min(6, Math.round(f.units / 25)))
        const empty = f.units === 0
        return (
          <Pick key={name} target={{ kind: 'backroom', id: name }} label={`${name} · ${f.units} units in backroom · ${f.dc} at DC`} labelY={layers * 0.45 + 1}>
            {(active) => (
              <group position={[x, 0, BACKROOM.z]}>
                <mesh position={[0, 0.08, 0]} receiveShadow castShadow>
                  <boxGeometry args={[2, 0.16, 1.4]} />
                  <meshStandardMaterial color={COLORS.pallet} />
                </mesh>
                {empty ? (
                  <mesh position={[0, 0.17, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                    <planeGeometry args={[1.8, 1.2]} />
                    <meshStandardMaterial color="#ef4b4b" transparent opacity={0.5} />
                  </mesh>
                ) : (
                  Array.from({ length: layers }, (_, k) => (
                    <mesh key={k} position={[0, 0.16 + 0.22 + k * 0.45, 0]} castShadow receiveShadow>
                      <boxGeometry args={[1.8, 0.42, 1.2]} />
                      <meshStandardMaterial color={active ? '#ffd9bf' : f.colour} />
                    </mesh>
                  ))
                )}
              </group>
            )}
          </Pick>
        )
      })}
      <Label position={[BACKROOM.x, 4.2, BACKROOM.z - 2.5]} text="Backroom" sub={`${total} units on hand`} />
      {/* Distribution centre at the end of the service road */}
      <Pick target={{ kind: 'kpi', id: 'requests' }} label={`Distribution centre · ${requests.length} replenishment request${requests.length === 1 ? '' : 's'}`} labelY={5}>
        {(active) => (
          <group position={[-50, 0, BACKROOM.z]}>
            <mesh position={[0, 2, 0]} castShadow receiveShadow>
              <boxGeometry args={[10, 4, 8]} />
              <meshStandardMaterial color={active ? '#fff1e6' : COLORS.wall} />
            </mesh>
            <mesh position={[0, 4.2, 0]} castShadow>
              <boxGeometry args={[10.6, 0.4, 8.6]} />
              <meshStandardMaterial color={COLORS.roof} />
            </mesh>
            <mesh position={[0, 3.4, 4.05]}>
              <boxGeometry args={[10, 0.5, 0.1]} />
              <meshStandardMaterial color={COLORS.brand} />
            </mesh>
          </group>
        )}
      </Pick>
      <Label position={[-50, 5.6, BACKROOM.z]} text="Distribution centre" sub={`${requests.length} replenishment request${requests.length === 1 ? '' : 's'}`} onClick={() => select({ kind: 'kpi', id: 'requests' })} />
    </group>
  )
}

/** The control room: one station per agent, lit while that agent is working. */
export function ControlRoom() {
  const active = useStore((s) => s.activeAgent)
  const selection = useStore((s) => s.selection)
  return (
    <group position={[0, 0, CONTROL_Z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.004, 0]} receiveShadow>
        <planeGeometry args={[30, 4.5]} />
        <meshStandardMaterial color="#e9e6f5" />
      </mesh>
      {AGENTS.map((a) => {
        const lit = active === a.id || (selection?.kind === 'agent' && selection.id === a.id)
        return (
          <Pick key={a.id} target={{ kind: 'agent', id: a.id }} label={`${a.label} agent · ${a.sub}`} labelY={2.2}>
            {(hover) => (
              <group position={[a.x, 0, 0]}>
                <mesh position={[0, 0.5, 0]} castShadow receiveShadow>
                  <boxGeometry args={[2.4, 1, 1.2]} />
                  <meshStandardMaterial color={hover ? '#fff1e6' : COLORS.wall} />
                </mesh>
                <mesh position={[0, 1.35, -0.3]} castShadow>
                  <boxGeometry args={[1.6, 0.7, 0.08]} />
                  <meshStandardMaterial color={lit ? '#9fc3ff' : '#2b2f45'} emissive={lit ? '#3b5bff' : '#000'} emissiveIntensity={lit ? 0.8 : 0} />
                </mesh>
                <mesh position={[0, 1.7, -0.3]}>
                  <sphereGeometry args={[0.12, 10, 10]} />
                  <meshStandardMaterial color={lit ? COLORS.brand : '#c8c6da'} emissive={lit ? COLORS.brand : '#000'} emissiveIntensity={lit ? 1 : 0} />
                </mesh>
              </group>
            )}
          </Pick>
        )
      })}
      <Label position={[-14, 2.6, 0]} text="Control room" sub="LangGraph supervisor" />
    </group>
  )
}
