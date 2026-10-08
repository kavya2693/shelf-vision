import { type ReactNode } from 'react'
import { Html } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import { useStore } from '../store'
import type { Selection } from '../types'

function same(a: Selection, b: Selection): boolean {
  return !!a && !!b && a.kind === b.kind && String(a.id) === String(b.id)
}

/**
 * Makes any group of meshes hoverable and clickable. `children` receives `active`
 * (hovered or selected) so the meshes can tint themselves; a pill label follows the
 * hover so every object in the world names itself.
 */
export function Pick({
  target,
  label,
  labelY = 4,
  children,
}: {
  target: Exclude<Selection, null>
  label?: string
  labelY?: number
  children: (active: boolean, selected: boolean) => ReactNode
}) {
  const hovered = useStore((s) => same(s.hover, target))
  const selected = useStore((s) => same(s.selection, target))
  const setHover = useStore((s) => s.setHover)
  const select = useStore((s) => s.select)
  return (
    <group
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation()
        select(target)
      }}
      onPointerOver={(e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation()
        setHover(target)
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={() => {
        setHover(null)
        document.body.style.cursor = ''
      }}
    >
      {children(hovered || selected, selected)}
      {hovered && label && (
        <Html position={[0, labelY, 0]} center zIndexRange={[8, 0]} style={{ pointerEvents: 'none' }}>
          <div className="hover-tag">{label}</div>
        </Html>
      )}
    </group>
  )
}

export function Label({
  position,
  text,
  sub,
  accent,
  onClick,
}: {
  position: [number, number, number]
  text: string
  sub?: string
  accent?: string
  onClick?: () => void
}) {
  return (
    <Html position={position} center zIndexRange={[5, 0]} style={{ pointerEvents: onClick ? 'auto' : 'none' }}>
      <div className={`world-label${onClick ? ' clickable' : ''}`} onClick={onClick}>
        {accent && <span className="world-label-dot" style={{ background: accent }} />}
        <span>{text}</span>
        {sub && <span className="world-label-sub">{sub}</span>}
      </div>
    </Html>
  )
}
