<script setup lang="ts">
/** 3D 静态图解:Three.js 场景,可旋转/缩放,不自动播放动画。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramShape, DiagramSpec } from '@/utils/diagramSpec'

const props = defineProps<{ spec: DiagramSpec }>()
const host = ref<HTMLDivElement | null>(null)
const error = ref('')

let renderer: import('three').WebGLRenderer | null = null
let scene: import('three').Scene | null = null
let camera: import('three').PerspectiveCamera | null = null
let controls: {
  dispose(): void
  update(): void
  addEventListener(type: string, fn: () => void): void
} | null = null
let observer: ResizeObserver | null = null
let disposed = false

function num(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function triple(value: unknown): [number, number, number] {
  if (!Array.isArray(value) || value.length < 2) return [0, 0, 0]
  return [num(value[0]), num(value[1]), num(value[2])]
}

function points(value: unknown): Array<[number, number, number]> {
  if (!Array.isArray(value)) return []
  return value.map((item) => triple(item))
}

function labelSprite(text: string, THREE: typeof import('three')): import('three').Sprite | null {
  if (!text) return null
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  canvas.width = 256
  canvas.height = 64
  ctx.fillStyle = 'rgba(10, 18, 30, 0.78)'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#d9f5ff'
  ctx.font = '24px sans-serif'
  ctx.fillText(text.slice(0, 30), 10, 40)
  const texture = new THREE.CanvasTexture(canvas)
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(1.6, 0.4, 1)
  return sprite
}

function addShape(shape: DiagramShape, THREE: typeof import('three'), root: import('three').Object3D): void {
  const x = num(shape.x)
  const y = num(shape.y)
  const z = num(shape.z)
  const material = new THREE.MeshStandardMaterial({
    color: 0x4cc9f0,
    metalness: 0.05,
    roughness: 0.55,
    transparent: true,
    opacity: 0.78,
  })
  const lineMaterial = new THREE.LineBasicMaterial({ color: 0x8be9fd })
  const kind = shape.kind
  if (kind === 'point') {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(num(shape.r) || 0.08, 16, 12), material)
    mesh.position.set(x, y, z)
    root.add(mesh)
  } else if (kind === 'segment' || kind === 'line' || kind === 'vector') {
    const from = triple(shape.from)
    const to = triple(shape.to)
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...from), new THREE.Vector3(...to),
    ])
    root.add(new THREE.Line(geometry, lineMaterial))
    if (kind === 'vector') {
      const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.28, 10), material)
      arrow.position.set(to[0], to[1], to[2])
      root.add(arrow)
    }
  } else if (kind === 'sphere') {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(num(shape.r) || 1, 24, 16), material)
    mesh.position.set(x, y, z)
    root.add(mesh)
  } else if (kind === 'box') {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(
      num(shape.width) || 1, num(shape.height) || 1, num(shape.depth) || 1), material)
    mesh.position.set(x, y, z)
    root.add(mesh)
  } else if (kind === 'cone') {
    const mesh = new THREE.Mesh(new THREE.ConeGeometry(num(shape.r) || 0.8, num(shape.height) || 1.6, 24), material)
    mesh.position.set(x, y, z)
    root.add(mesh)
  } else if (kind === 'cylinder') {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(
      num(shape.r) || 0.7, num(shape.r) || 0.7, num(shape.height) || 1.5, 24), material)
    mesh.position.set(x, y, z)
    root.add(mesh)
  } else if (kind === 'plane') {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(
      num(shape.width) || 3, num(shape.height) || 3), material)
    mesh.position.set(x, y, z)
    mesh.rotation.x = -Math.PI / 2
    root.add(mesh)
  } else if (kind === 'circle') {
    const mesh = new THREE.Mesh(new THREE.CircleGeometry(num(shape.r) || 1, 32), material)
    mesh.position.set(x, y, z)
    root.add(mesh)
  } else if (kind === 'polygon' || kind === 'curve' || kind === 'surface') {
    const pts = points(shape.points)
    if (pts.length) {
      const geometry = new THREE.BufferGeometry().setFromPoints(pts.map((p) => new THREE.Vector3(...p)))
      if (kind === 'curve') root.add(new THREE.Line(geometry, lineMaterial))
      else if (kind === 'surface') {
        root.add(new THREE.Points(geometry, new THREE.PointsMaterial({ color: 0x4cc9f0, size: 0.05 })))
      } else {
        const shapeObj = new THREE.Mesh(new THREE.BufferGeometry(), material)
        shapeObj.geometry.setFromPoints(pts.map((p) => new THREE.Vector3(...p)))
        root.add(shapeObj)
      }
    }
  }
  if (shape.label) {
    const sprite = labelSprite(String(shape.label), THREE)
    if (sprite) {
      sprite.position.set(x, y + 0.22, z)
      root.add(sprite)
    }
  }
}

async function boot(): Promise<void> {
  const el = host.value
  if (!el) return
  try {
    const THREE = await import('three')
    const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
    if (disposed) return
    scene = new THREE.Scene()
    scene.background = null
    camera = new THREE.PerspectiveCamera(45, el.clientWidth / Math.max(1, el.clientHeight), 0.1, 200)
    camera.position.set(5.5, 4.5, 7.5)
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(el.clientWidth, Math.max(220, el.clientHeight))
    el.appendChild(renderer.domElement)
    const root = new THREE.Group()
    scene.add(root)
    scene.add(new THREE.AmbientLight(0xffffff, 0.9))
    const light = new THREE.DirectionalLight(0xffffff, 1.2)
    light.position.set(4, 8, 6)
    scene.add(light)
    for (const shape of props.spec.shapes) addShape(shape, THREE, root)
    for (const note of props.spec.annotations) {
      const sprite = labelSprite(note.text, THREE)
      if (sprite) {
        sprite.position.set(note.x, note.y, 0)
        scene.add(sprite)
      }
    }
    const bounds = new THREE.Box3().setFromObject(root)
    if (!bounds.isEmpty()) {
      const center = bounds.getCenter(new THREE.Vector3())
      const size = bounds.getSize(new THREE.Vector3()).length()
      controls = new OrbitControls(camera, renderer.domElement)
      controls.update()
      controls.addEventListener('change', () => renderer?.render(scene!, camera!))
      camera.position.set(center.x + size * 1.2, center.y + size * 0.8, center.z + size * 1.2)
      camera.lookAt(center)
    } else {
      controls = new OrbitControls(camera, renderer.domElement)
      controls.update()
      controls.addEventListener('change', () => renderer?.render(scene!, camera!))
    }
    renderer.render(scene, camera)
    observer = new ResizeObserver(() => {
      if (!el || !renderer || !camera) return
      const w = Math.max(1, el.clientWidth)
      const h = Math.max(220, el.clientHeight)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
      renderer.render(scene!, camera)
    })
    observer.observe(el)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '3D 渲染失败'
  }
}

function dispose(): void {
  disposed = true
  observer?.disconnect()
  observer = null
  controls?.dispose()
  controls = null
  if (scene) {
    scene.traverse((obj) => {
      const item = obj as import('three').Mesh
      item.geometry?.dispose?.()
      const material = item.material as import('three').Material | undefined
      if (material) {
        const mapped = material as import('three').MeshStandardMaterial
        mapped.map?.dispose()
        material.dispose()
      }
    })
    scene.clear()
    scene = null
  }
  renderer?.dispose()
  renderer?.domElement.remove()
  renderer = null
  camera = null
}

onMounted(() => { void boot() })
onBeforeUnmount(dispose)
</script>

<template>
  <div ref="host" class="diagram-3d">
    <p v-if="error" class="diagram-3d-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.diagram-3d {
  position: relative;
  min-height: 220px;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-card);
  touch-action: none;
}

.diagram-3d-error {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  font-size: 11px;
}
</style>
