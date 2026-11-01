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

/** 数学坐标 (x, y, z) → Three.js (x, z, y),让 z=f(x,y) 的 z 轴朝上。 */
function vec3(value: unknown, THREE: typeof import('three')): import('three').Vector3 {
  const [x, y, z] = triple(value)
  return new THREE.Vector3(x, z, y)
}

function points(value: unknown): Array<[number, number, number]> {
  if (!Array.isArray(value)) return []
  return value.map((item) => triple(item))
}

function labelSprite(
  text: string,
  THREE: typeof import('three'),
  scale = 1,
): import('three').Sprite | null {
  if (!text) return null
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  canvas.width = 512
  canvas.height = 128
  ctx.fillStyle = 'rgba(10, 18, 30, 0.78)'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#d9f5ff'
  ctx.font = '36px sans-serif'
  ctx.fillText(text.slice(0, 40), 12, 74)
  const texture = new THREE.CanvasTexture(canvas)
  const material = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthTest: false,
  })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(3.2 * scale, 0.8 * scale, 1)
  sprite.renderOrder = 20
  return sprite
}

function markerSprite(
  text: string,
  THREE: typeof import('three'),
  scale: number,
): import('three').Sprite | null {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  canvas.width = 128
  canvas.height = 128
  ctx.fillStyle = 'rgba(10, 18, 30, 0.88)'
  ctx.beginPath()
  ctx.arc(64, 64, 58, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = '#4cc9f0'
  ctx.lineWidth = 6
  ctx.stroke()
  ctx.fillStyle = '#d9f5ff'
  ctx.font = 'bold 64px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text.slice(0, 3), 64, 68)
  const texture = new THREE.CanvasTexture(canvas)
  const material = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthTest: false,
  })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(scale, scale, 1)
  sprite.renderOrder = 20
  return sprite
}

/** 曲面跨度大时,点和箭头默认尺寸会小到看不见;按场景尺度放大。 */
function sceneUnit(shapes: DiagramShape[]): number {
  let span = 0
  for (const shape of shapes) {
    if (shape.kind === 'surface' && Array.isArray(shape.points)) {
      const xs: number[] = []
      const ys: number[] = []
      const zs: number[] = []
      for (const item of shape.points) {
        const point = triple(item)
        xs.push(point[0]); ys.push(point[1]); zs.push(point[2])
      }
      if (xs.length) {
        span = Math.max(span,
          Math.max(...xs) - Math.min(...xs),
          Math.max(...ys) - Math.min(...ys),
          Math.max(...zs) - Math.min(...zs))
      }
    }
  }
  return Math.max(0.08, span / 28)
}

function addAxes(
  THREE: typeof import('three'),
  root: import('three').Object3D,
  bounds: import('three').Box3,
  labelScale = 1,
): void {
  const extent = (a: number, b: number): number => Math.max(1, Math.abs(a), Math.abs(b))
  // bounds 已是 Three 坐标:y 是数学 z,x/z 是数学 x/y。
  const ex = extent(bounds.isEmpty() ? -3 : bounds.min.x, bounds.isEmpty() ? 3 : bounds.max.x)
  const ey = extent(bounds.isEmpty() ? -3 : bounds.min.z, bounds.isEmpty() ? 3 : bounds.max.z)
  const z0 = bounds.isEmpty() ? -3 : Math.min(0, bounds.min.y)
  const z1 = bounds.isEmpty() ? 3 : Math.max(0, bounds.max.y)
  const material = new THREE.LineBasicMaterial({
    color: 0x64748b, depthTest: false, transparent: true, opacity: 0.6,
  })
  const axes: Array<[[number, number, number], [number, number, number], string]> = [
    [[-ex, 0, 0], [ex, 0, 0], 'x'],
    [[0, 0, -ey], [0, 0, ey], 'y'],
    [[0, z0, 0], [0, z1, 0], 'z'],
  ]
  for (const [from, to, label] of axes) {
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...from), new THREE.Vector3(...to),
    ])
    root.add(new THREE.Line(geometry, material))
    const sprite = labelSprite(label, THREE, labelScale)
    if (sprite) {
      sprite.position.set(...to)
      root.add(sprite)
    }
  }
}

function addSurface(
  shape: DiagramShape,
  THREE: typeof import('three'),
  root: import('three').Object3D,
  color: import('three').Color,
): boolean {
  const pts = points(shape.points)
  if (!pts.length) return false
  const rows = Math.trunc(num(shape.rows))
  const cols = Math.trunc(num(shape.cols))
  if (rows >= 2 && cols >= 2 && pts.length >= rows * cols) {
    const positions = new Float32Array(rows * cols * 3)
    for (let index = 0; index < rows * cols; index += 1) {
      positions[index * 3] = pts[index][0]
      positions[index * 3 + 1] = pts[index][2]
      positions[index * 3 + 2] = pts[index][1]
    }
    const indices: number[] = []
    for (let row = 0; row < rows - 1; row += 1) {
      for (let col = 0; col < cols - 1; col += 1) {
        const a = row * cols + col
        const b = a + 1
        const c = a + cols
        const d = c + 1
        indices.push(a, c, b, b, c, d)
      }
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setIndex(indices)
    geometry.computeVertexNormals()
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color, side: THREE.DoubleSide, transparent: true, opacity: 0.78,
      roughness: 0.6, metalness: 0.04,
    }))
    root.add(mesh)
    const wire = new THREE.LineSegments(
      new THREE.WireframeGeometry(geometry),
      new THREE.LineBasicMaterial({ color: 0x8be9fd, transparent: true, opacity: 0.24 }),
    )
    root.add(wire)
    return true
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(
    pts.map((item) => vec3(item, THREE)),
  )
  root.add(new THREE.Points(geometry, new THREE.PointsMaterial({
    color, size: 0.08, sizeAttenuation: true,
  })))
  return true
}

function addArrow(
  from: [number, number, number],
  to: [number, number, number],
  THREE: typeof import('three'),
  root: import('three').Object3D,
  material: import('three').Material,
  unit: number,
): void {
  const start = vec3(from, THREE)
  const end = vec3(to, THREE)
  const direction = end.clone().sub(start)
  const length = direction.length()
  if (length < 1e-6) return
  const headLength = Math.min(length * 0.35, Math.max(unit * 1.8, length * 0.2))
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(Math.max(unit * 0.35, headLength * 0.32), headLength, 12),
    material,
  )
  cone.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 1, 0), direction.clone().normalize(),
  )
  cone.position.copy(end).addScaledVector(direction.normalize(), -headLength / 2)
  cone.renderOrder = 11
  root.add(cone)
}

function addShape(
  shape: DiagramShape,
  THREE: typeof import('three'),
  root: import('three').Object3D,
  unit = 0.08,
  labelScale = 1,
): void {
  const x = num(shape.x)
  const y = num(shape.y)
  const z = num(shape.z)
  let color = new THREE.Color(0x4cc9f0)
  if (typeof shape.color === 'string' && shape.color) {
    try {
      color = new THREE.Color(shape.color)
    } catch {
      /* 非法颜色回退默认色 */
    }
  }
  const material = new THREE.MeshStandardMaterial({
    color,
    metalness: 0.05,
    roughness: 0.55,
    transparent: true,
    opacity: 0.78,
  })
  const lineMaterial = new THREE.LineBasicMaterial({ color })
  const overlayLine = new THREE.LineBasicMaterial({
    color, depthTest: false, transparent: true, opacity: 0.95,
  })
  const axisMaterial = new THREE.LineBasicMaterial({
    color: 0x8be9fd, depthTest: false, transparent: true, opacity: 0.45,
  })
  const kind = shape.kind
  if (kind === 'point') {
    material.depthTest = false
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(num(shape.r) || unit, 16, 12), material,
    )
    mesh.position.copy(vec3([x, y, z], THREE))
    mesh.renderOrder = 10
    root.add(mesh)
  } else if (kind === 'segment' || kind === 'line' || kind === 'vector' || kind === 'axis') {
    const from = triple(shape.from)
    const to = triple(shape.to)
    const geometry = new THREE.BufferGeometry().setFromPoints([
      vec3(from, THREE), vec3(to, THREE),
    ])
    const line = new THREE.Line(
      geometry,
      kind === 'axis' ? axisMaterial
        : (kind === 'vector' ? overlayLine : lineMaterial),
    )
    line.renderOrder = kind === 'axis' ? 5 : 10
    root.add(line)
    if (kind === 'vector') {
      material.depthTest = false
      const start = vec3(from, THREE)
      const end = vec3(to, THREE)
      if (start.distanceTo(end) > 1e-6) {
        const tube = new THREE.Mesh(
          new THREE.TubeGeometry(
            new THREE.LineCurve3(start, end), 1,
            Math.max(unit * 0.12, 0.012), 6, false,
          ),
          material,
        )
        tube.renderOrder = 10
        root.add(tube)
      }
      addArrow(from, to, THREE, root, material, unit)
    }
  } else if (kind === 'sphere') {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(num(shape.r) || 1, 24, 16), material)
    mesh.position.copy(vec3([x, y, z], THREE))
    root.add(mesh)
  } else if (kind === 'box') {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(
      num(shape.width) || 1, num(shape.height) || 1, num(shape.depth) || 1), material)
    mesh.position.copy(vec3([x, y, z], THREE))
    root.add(mesh)
  } else if (kind === 'cone') {
    const mesh = new THREE.Mesh(new THREE.ConeGeometry(num(shape.r) || 0.8, num(shape.height) || 1.6, 24), material)
    mesh.position.copy(vec3([x, y, z], THREE))
    root.add(mesh)
  } else if (kind === 'cylinder') {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(
      num(shape.r) || 0.7, num(shape.r) || 0.7, num(shape.height) || 1.5, 24), material)
    mesh.position.copy(vec3([x, y, z], THREE))
    root.add(mesh)
  } else if (kind === 'plane') {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(
      num(shape.width) || 3, num(shape.height) || 3), material)
    mesh.position.copy(vec3([x, y, z], THREE))
    if (Array.isArray(shape.normal) && shape.normal.length >= 3) {
      const normal = vec3(shape.normal, THREE)
      if (normal.lengthSq() > 1e-8) {
        mesh.quaternion.setFromUnitVectors(
          new THREE.Vector3(0, 0, 1), normal.normalize(),
        )
      }
    } else {
      mesh.rotation.x = -Math.PI / 2
    }
    root.add(mesh)
  } else if (kind === 'circle') {
    const mesh = new THREE.Mesh(new THREE.CircleGeometry(num(shape.r) || 1, 32), material)
    mesh.position.copy(vec3([x, y, z], THREE))
    root.add(mesh)
  } else if (kind === 'polygon') {
    const pts = points(shape.points)
    if (pts.length) {
      const geometry = new THREE.BufferGeometry().setFromPoints(
        pts.map((item) => vec3(item, THREE)),
      )
      root.add(new THREE.LineLoop(geometry, lineMaterial))
    }
  } else if (kind === 'curve') {
    const pts = points(shape.points)
    if (pts.length) {
      const geometry = new THREE.BufferGeometry().setFromPoints(
        pts.map((item) => vec3(item, THREE)),
      )
      root.add(new THREE.Line(geometry, lineMaterial))
    }
  } else if (kind === 'surface') {
    addSurface(shape, THREE, root, color)
  }
  if (shape.label) {
    const vectorLabels = props.spec.shapes.filter(
      (item) => item.kind === 'vector' && item.label,
    ).length
    const auxiliaryVector = kind === 'vector' && vectorLabels > 2
      && !/梯度|∇|gradient/i.test(String(shape.label))
    if (!auxiliaryVector) {
      const sprite = labelSprite(String(shape.label), THREE, labelScale)
      if (sprite) {
        const from = triple(shape.from)
        const to = triple(shape.to)
        const hasLine = ['segment', 'line', 'vector', 'axis'].includes(kind)
        const anchor = hasLine
          ? vec3([
            (from[0] + to[0]) / 2,
            (from[1] + to[1]) / 2,
            (from[2] + to[2]) / 2,
          ], THREE)
          : vec3([x, y, z], THREE)
        if (!hasLine) anchor.y += 0.22
        sprite.position.copy(anchor)
        root.add(sprite)
      }
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
    renderer.setSize(el.clientWidth, Math.max(340, el.clientHeight))
    el.appendChild(renderer.domElement)
    const root = new THREE.Group()
    scene.add(root)
    scene.add(new THREE.AmbientLight(0xffffff, 0.9))
    const light = new THREE.DirectionalLight(0xffffff, 1.2)
    light.position.set(4, 8, 6)
    scene.add(light)
    const unit = sceneUnit(props.spec.shapes)
    const labelScale = Math.max(1, Math.min(2.4, unit * 3))
    for (const shape of props.spec.shapes) {
      addShape(shape, THREE, root, unit, labelScale)
    }
    const shapeBounds = new THREE.Box3().setFromObject(root)
    // 三维图解先给出坐标轴,曲面和方向才有空间参照。
    addAxes(THREE, root, shapeBounds, labelScale)
    const notePositions = new Map<string, number>()
    props.spec.annotations.forEach((note, index) => {
      // 3D 里长文字直接贴图会叠在一起;用编号标记,正文放到画布下方图例。
      const sprite = markerSprite(String(index + 1), THREE, Math.max(0.35, unit * 1.5))
      if (!sprite) return
      const key = `${note.x}|${note.y}|${num(note.z)}`
      const repeat = notePositions.get(key) || 0
      notePositions.set(key, repeat + 1)
      sprite.position.copy(vec3([note.x, note.y, num(note.z)], THREE))
      sprite.position.y += repeat * unit * 0.75
      root.add(sprite)
    })
    const bounds = shapeBounds.isEmpty() ? null : shapeBounds
    if (bounds) {
      const sphere = bounds.getBoundingSphere(new THREE.Sphere())
      const radius = Math.max(1, sphere.radius)
      const center = sphere.center
      camera.far = Math.max(200, radius * 20)
      camera.updateProjectionMatrix()
      controls = new OrbitControls(camera, renderer.domElement)
      controls.update()
      controls.addEventListener('change', () => renderer?.render(scene!, camera!))
      camera.position.set(
        center.x + radius * 1.8,
        center.y + radius * 1.25,
        center.z + radius * 2.1,
      )
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
      const h = Math.max(340, el.clientHeight)
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
  renderer?.forceContextLoss()
  renderer?.domElement.remove()
  renderer = null
  camera = null
}

onMounted(() => { void boot() })
onBeforeUnmount(dispose)
</script>

<template>
  <div class="diagram-3d-wrap">
    <div ref="host" class="diagram-3d">
      <p v-if="error" class="diagram-3d-error">{{ error }}</p>
    </div>
    <ol v-if="props.spec.annotations.length" class="diagram-3d-legend">
      <li v-for="(note, index) in props.spec.annotations" :key="index">
        <span class="diagram-3d-num">{{ index + 1 }}</span>{{ note.text }}
      </li>
    </ol>
  </div>
</template>

<style scoped>
.diagram-3d-wrap {
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-card);
}

.diagram-3d {
  position: relative;
  min-height: 340px;
  overflow: hidden;
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

.diagram-3d-legend {
  margin: 0;
  padding: 6px 10px 8px 12px;
  list-style: none;
  border-top: 1px solid var(--line);
  color: var(--text-dim);
  font-size: 10px;
  line-height: 1.6;
}

.diagram-3d-num {
  display: inline-block;
  min-width: 15px;
  margin-right: 5px;
  color: var(--cyan);
  font-family: var(--font-tech);
}
</style>
