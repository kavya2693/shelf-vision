import { useMemo } from 'react'
import { useStore } from '../store'
import { BAY, COLORS, MM, STATUS_COLORS, bayTransform, boardY } from '../layout'
import type { Bay, SlotRow } from '../types'
import { Label, Pick } from './Pick'

const rgb = (c: [number, number, number]) => `rgb(${c[0]},${c[1]},${c[2]})`

function Slot({ slot }: { slot: SlotRow }) {
  const colour = useStore((s) => s.colour)
  const w = slot.pack_w * MM
  const h = slot.pack_h * MM
  const x0 = slot.index - BAY.width / 2 + 0.05
  const y = boardY(slot.shelf)
  const faulty = slot.status !== 'ok'
  const statusColour = STATUS_COLORS[slot.status]
  const packColour = colour === 'status' ? statusColour : faulty ? statusColour : rgb(slot.rgb)
  // What is drawn mirrors the confirmed status: an empty slot shows the back panel with a red
  // marker on the board, a short-faced slot loses its last facing, a misplaced slot gets a foreign
  // dark pack at the front.
  const facings = slot.status === 'out_of_stock' ? 0 : slot.status === 'wrong_facings' ? Math.max(1, slot.facings - 1) : slot.facings
  return (
    <Pick target={{ kind: 'slot', id: slot.slot_id }} label={`${slot.slot_id} · ${slot.sku} · ${slot.status.replace('_', ' ')}`} labelY={y + h + 0.5}>
      {(active, selected) => (
        <group position={[x0 + 0.45, 0, 0]}>
          {/* invisible hit box over the whole slot so empty slots are clickable */}
          <mesh position={[0, y + BAY.pitch / 2 - BAY.board, 0]}>
            <boxGeometry args={[0.98, BAY.pitch - BAY.board, BAY.depth - 0.2]} />
            <meshStandardMaterial transparent opacity={active ? 0.18 : 0.001} color={COLORS.hover} depthWrite={false} />
          </mesh>
          {Array.from({ length: facings }, (_, j) => {
            const foreign = slot.status === 'misplaced' && j === 0
            return (
              <mesh key={j} position={[-0.45 + 0.05 + j * w + w / 2, y + h / 2, 0.25]} castShadow receiveShadow>
                <boxGeometry args={[w * 0.92, h, 0.6]} />
                <meshStandardMaterial color={foreign ? '#5a5f7a' : packColour} emissive={selected ? COLORS.selected : '#000'} emissiveIntensity={selected ? 0.35 : 0} />
              </mesh>
            )
          })}
          {slot.status === 'out_of_stock' && (
            <mesh position={[0, y + 0.02, 0.2]} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[0.9, 0.9]} />
              <meshStandardMaterial color={STATUS_COLORS.out_of_stock} transparent opacity={0.75} />
            </mesh>
          )}
          {/* price tag on the rail; missing-tag slots show a blue stub instead */}
          <mesh position={[-0.45 + 0.22, y - BAY.board / 2, BAY.depth / 2 + 0.01]}>
            <boxGeometry args={[0.36, 0.09, 0.02]} />
            <meshStandardMaterial color={slot.status === 'missing_tag' ? STATUS_COLORS.missing_tag : COLORS.tag} />
          </mesh>
          {slot.task_state === 'pending_review' && (
            <mesh position={[0, y + h + 0.25, 0.3]}>
              <sphereGeometry args={[0.12, 10, 10]} />
              <meshStandardMaterial color="#8b5cf6" emissive="#8b5cf6" emissiveIntensity={0.6} />
            </mesh>
          )}
        </group>
      )}
    </Pick>
  )
}

function BayUnit({ bay, slots }: { bay: Bay; slots: SlotRow[] }) {
  const { x, z, rotation } = bayTransform(bay.aisle, bay.side)
  const faults = slots.filter((s) => s.status !== 'ok').length
  const labelColour = faults === 0 ? STATUS_COLORS.ok : faults >= 4 ? STATUS_COLORS.out_of_stock : STATUS_COLORS.wrong_facings
  const select = useStore((s) => s.select)
  return (
    <group position={[x, 0, z]} rotation={[0, rotation, 0]}>
      {/* back panel and sides */}
      <mesh position={[0, BAY.height / 2, -BAY.depth / 2]} castShadow receiveShadow>
        <boxGeometry args={[BAY.width + 0.2, BAY.height, 0.12]} />
        <meshStandardMaterial color={COLORS.shelfBack} />
      </mesh>
      {[-1, 1].map((k) => (
        <mesh key={k} position={[k * (BAY.width / 2 + 0.06), BAY.height / 2, 0]} castShadow receiveShadow>
          <boxGeometry args={[0.1, BAY.height, BAY.depth]} />
          <meshStandardMaterial color={COLORS.shelf} />
        </mesh>
      ))}
      {Array.from({ length: BAY.shelves }, (_, s) => (
        <group key={s}>
          <mesh position={[0, boardY(s) - BAY.board / 2, 0]} castShadow receiveShadow>
            <boxGeometry args={[BAY.width, BAY.board, BAY.depth]} />
            <meshStandardMaterial color={COLORS.shelf} />
          </mesh>
          <mesh position={[0, boardY(s) - BAY.board / 2, BAY.depth / 2 + 0.005]}>
            <boxGeometry args={[BAY.width, BAY.board * 0.8, 0.01]} />
            <meshStandardMaterial color={COLORS.shelfEdge} />
          </mesh>
        </group>
      ))}
      <mesh position={[0, BAY.height + 0.08, 0]} castShadow>
        <boxGeometry args={[BAY.width + 0.2, 0.16, BAY.depth]} />
        <meshStandardMaterial color={COLORS.shelf} />
      </mesh>
      {slots.map((s) => (
        <Slot key={s.slot_id} slot={s} />
      ))}
      <Label position={[0, BAY.height + 0.9, 0]} text={`Bay ${bay.bay_id}`} sub={faults ? `${faults} of ${slots.length} slots off plan` : 'as planned'} accent={labelColour} onClick={() => select({ kind: 'bay', id: bay.bay_id })} />
    </group>
  )
}

export function Bays() {
  const bays = useStore((s) => s.snap?.bays ?? [])
  const slots = useStore((s) => s.snap?.slots ?? [])
  const byBay = useMemo(() => {
    const m = new Map<string, SlotRow[]>()
    for (const s of slots) m.set(s.bay_id, [...(m.get(s.bay_id) ?? []), s])
    return m
  }, [slots])
  return (
    <group>
      {bays.map((b) => (
        <BayUnit key={b.bay_id} bay={b} slots={byBay.get(b.bay_id) ?? []} />
      ))}
    </group>
  )
}
