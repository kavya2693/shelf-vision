import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { MapControls } from '@react-three/drei'
import { useStore } from '../store'
import { Ground } from './Ground'
import { Bays } from './Bays'
import { Cameras } from './Cameras'
import { Backroom, ControlRoom } from './Backroom'

export function World() {
  const select = useStore((s) => s.select)
  return (
    <Canvas
      shadows="soft"
      dpr={[1, 1.75]}
      camera={{ position: [3, 38, 48], fov: 30, near: 1, far: 600 }}
      gl={{ antialias: true, powerPreference: 'high-performance' }}
      onPointerMissed={() => select(null)}
      style={{ position: 'absolute', inset: 0 }}
    >
      <color attach="background" args={['#ece9f8']} />
      <fog attach="fog" args={['#ece9f8', 160, 320]} />
      <hemisphereLight args={['#ffffff', '#cfc9ec', 0.6]} />
      <ambientLight intensity={0.25} />
      <directionalLight
        position={[40, 60, 30]}
        intensity={2.2}
        castShadow
        shadow-mapSize={[4096, 4096]}
        shadow-bias={-0.0004}
        shadow-camera-left={-80}
        shadow-camera-right={80}
        shadow-camera-top={80}
        shadow-camera-bottom={-80}
        shadow-camera-near={10}
        shadow-camera-far={220}
      />
      <Suspense fallback={null}>
        <Ground />
        <Bays />
        <Cameras />
        <Backroom />
        <ControlRoom />
      </Suspense>
      <MapControls
        target={[0, 1, -2]}
        enableDamping
        dampingFactor={0.08}
        minDistance={8}
        maxDistance={200}
        maxPolarAngle={Math.PI / 2.2}
        minPolarAngle={0.2}
        screenSpacePanning={false}
      />
    </Canvas>
  )
}
