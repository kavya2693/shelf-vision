import { useMemo } from 'react'
import * as THREE from 'three'
import { useStore } from '../store'
import { BAY, COLORS, STATUS_COLORS, bayTransform, cameraPosition } from '../layout'
import type { Camera } from '../types'
import { Pick } from './Pick'

function CameraUnit({ cam, aisle, side }: { cam: Camera; aisle: number; side: 'L' | 'R' }) {
  const pos = cameraPosition(aisle, side)
  const bay = bayTransform(aisle, side)
  const target = new THREE.Vector3(bay.x, BAY.height / 2, bay.z)
  const from = new THREE.Vector3(...pos)
  const dir = target.clone().sub(from)
  const len = dir.length()
  // A cone whose apex sits at the lens and whose base covers the bay face.
  const quat = useMemo(() => {
    const q = new THREE.Quaternion()
    q.setFromUnitVectors(new THREE.Vector3(0, -1, 0), dir.clone().normalize())
    return q
  }, [pos[0], pos[1], pos[2], bay.x, bay.z]) // eslint-disable-line react-hooks/exhaustive-deps
  const slots = useStore((s) => s.snap?.slots.filter((r) => r.bay_id === cam.bay_id) ?? [])
  const faults = slots.filter((s) => s.status !== 'ok').length
  const tone = faults === 0 ? STATUS_COLORS.ok : faults >= 4 ? STATUS_COLORS.out_of_stock : STATUS_COLORS.wrong_facings
  const yaw = Math.atan2(dir.x, dir.z)
  return (
    <Pick target={{ kind: 'camera', id: cam.camera_id }} label={`${cam.camera_id} · ${cam.label} · ${cam.boxes} boxes${cam.shoppers ? ` · ${cam.shoppers} shopper` : ''}`} labelY={1.1}>
      {(active, selected) => (
        <group position={pos}>
          {/* pole */}
          <mesh position={[0, -pos[1] / 2, 0]} castShadow>
            <cylinderGeometry args={[0.06, 0.08, pos[1], 8]} />
            <meshStandardMaterial color="#b9b7cc" />
          </mesh>
          {/* housing, pointed at the bay */}
          <group rotation={[0, yaw, 0]}>
            <mesh position={[0, 0, 0.25]} castShadow>
              <boxGeometry args={[0.42, 0.3, 0.7]} />
              <meshStandardMaterial color={active ? COLORS.hover : COLORS.camera} />
            </mesh>
            <mesh position={[0, 0, 0.62]} rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[0.1, 0.13, 0.12, 12]} />
              <meshStandardMaterial color="#8fb3ff" emissive="#3b5bff" emissiveIntensity={0.5} />
            </mesh>
          </group>
          {/* recording light */}
          <mesh position={[0, 0.25, 0]}>
            <sphereGeometry args={[0.07, 8, 8]} />
            <meshStandardMaterial color={tone} emissive={tone} emissiveIntensity={0.9} />
          </mesh>
          {/* view cone */}
          <mesh quaternion={quat} position={[dir.x / 2, dir.y / 2, dir.z / 2]} raycast={() => null}>
            <coneGeometry args={[BAY.width * 0.62, len, 24, 1, true]} />
            <meshBasicMaterial color={selected || active ? COLORS.hover : COLORS.cone} transparent opacity={selected ? 0.22 : active ? 0.16 : 0.07} side={THREE.DoubleSide} depthWrite={false} />
          </mesh>
        </group>
      )}
    </Pick>
  )
}

export function Cameras() {
  const cams = useStore((s) => s.snap?.cameras ?? [])
  const bays = useStore((s) => s.snap?.bays ?? [])
  return (
    <group>
      {cams.map((c) => {
        const b = bays.find((x) => x.bay_id === c.bay_id)
        return b ? <CameraUnit key={c.camera_id} cam={c} aisle={b.aisle} side={b.side} /> : null
      })}
    </group>
  )
}
