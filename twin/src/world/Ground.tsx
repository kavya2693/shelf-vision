import { useMemo } from 'react'
import * as THREE from 'three'
import { AISLE_Z, BACKROOM, COLORS, STORE } from '../layout'

function mulberry(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function Trees() {
  const positions = useMemo(() => {
    const out: [number, number, number][] = []
    const rnd = mulberry(11)
    for (let x = -46; x <= 46; x += 5) out.push([x + (rnd() - 0.5) * 2, 0, 26 + (rnd() - 0.5) * 3])
    for (let z = -30; z <= 24; z += 5.5) out.push([-44 + (rnd() - 0.5) * 3, 0, z + (rnd() - 0.5) * 2])
    for (let z = -30; z <= 24; z += 5.5) out.push([44 + (rnd() - 0.5) * 3, 0, z + (rnd() - 0.5) * 2])
    return out
  }, [])
  const foliage = useMemo(() => {
    const g = new THREE.ConeGeometry(1.3, 3.4, 7)
    g.translate(0, 2.7, 0)
    return g
  }, [])
  const trunk = useMemo(() => {
    const g = new THREE.CylinderGeometry(0.22, 0.28, 1.2, 6)
    g.translate(0, 0.6, 0)
    return g
  }, [])
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const setup = (mesh: THREE.InstancedMesh | null, colored: boolean) => {
    if (!mesh) return
    const rnd = mulberry(5)
    positions.forEach((p, i) => {
      const s = 0.75 + rnd() * 0.6
      dummy.position.set(p[0], p[1], p[2])
      dummy.scale.set(s, s, s)
      dummy.rotation.y = rnd() * Math.PI
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      if (colored) mesh.setColorAt(i, new THREE.Color(rnd() > 0.5 ? COLORS.tree : COLORS.treeDark))
      else rnd()
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }
  return (
    <group>
      <instancedMesh ref={(m) => setup(m, true)} args={[foliage, undefined, positions.length]} castShadow receiveShadow>
        <meshStandardMaterial color={COLORS.tree} flatShading />
      </instancedMesh>
      <instancedMesh ref={(m) => setup(m, false)} args={[trunk, undefined, positions.length]} castShadow>
        <meshStandardMaterial color={COLORS.trunk} />
      </instancedMesh>
    </group>
  )
}

export function Ground() {
  const { width, depth, wallHeight } = STORE
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} receiveShadow>
        <planeGeometry args={[220, 220]} />
        <meshStandardMaterial color={COLORS.ground} />
      </mesh>
      {/* Sales floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[width, depth]} />
        <meshStandardMaterial color={COLORS.floor} />
      </mesh>
      {/* Walkway in front of each gondola run */}
      {AISLE_Z.map((z) => (
        <mesh key={z} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.005, z + 2.2]} receiveShadow>
          <planeGeometry args={[22, 4.6]} />
          <meshStandardMaterial color={COLORS.floorLine} />
        </mesh>
      ))}
      {/* Low walls so the camera still sees inside */}
      {[
        { p: [0, wallHeight / 2, -depth / 2] as [number, number, number], s: [width, wallHeight, 0.3] as [number, number, number] },
        { p: [-width / 2, wallHeight / 2, 0] as [number, number, number], s: [0.3, wallHeight, depth] as [number, number, number] },
        { p: [width / 2, wallHeight / 2, 0] as [number, number, number], s: [0.3, wallHeight, depth] as [number, number, number] },
      ].map((w, i) => (
        <mesh key={i} position={w.p} castShadow receiveShadow>
          <boxGeometry args={w.s} />
          <meshStandardMaterial color={COLORS.wallShade} transparent opacity={0.55} />
        </mesh>
      ))}
      {/* Front fascia with the brand stripe, entrance in the middle */}
      {[-1, 1].map((k) => (
        <mesh key={k} position={[k * (width / 4 + 3), 1.0, depth / 2]} castShadow>
          <boxGeometry args={[width / 2 - 6, 2.0, 0.3]} />
          <meshStandardMaterial color={COLORS.wall} />
        </mesh>
      ))}
      <mesh position={[0, 2.2, depth / 2]} castShadow={false}>
        <boxGeometry args={[width, 0.5, 0.35]} />
        <meshStandardMaterial color={COLORS.brand} />
      </mesh>
      {/* Backroom floor and wall */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[BACKROOM.x, 0, BACKROOM.z]} receiveShadow>
        <planeGeometry args={[BACKROOM.width, BACKROOM.depth]} />
        <meshStandardMaterial color="#e6e3f3" />
      </mesh>
      <mesh position={[BACKROOM.x, wallHeight / 2, BACKROOM.z - BACKROOM.depth / 2]} receiveShadow>
        <boxGeometry args={[BACKROOM.width, wallHeight, 0.3]} />
        <meshStandardMaterial color={COLORS.wallShade} transparent opacity={0.55} />
      </mesh>
      {/* Service road to the distribution centre */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[-32, 0.01, BACKROOM.z]} receiveShadow>
        <planeGeometry args={[34, 4.5]} />
        <meshStandardMaterial color={COLORS.road} />
      </mesh>
      <Trees />
    </group>
  )
}
