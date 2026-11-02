<script setup lang="ts">
/** 3D 静态图解:Three.js 场景,可旋转/缩放,不自动播放动画。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramShape, DiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'

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
let contextLostHandler: ((event: Event) => void) | null = null
let disposed = false

function num(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function triple(value: unknown): [number, number, number] {
  if (!Array.isArray(value) || value.length < 2) return [0, 0, 0]
  return [num(value[0]), num(value[1]), num(value[2])]
}

/** 数学坐标 (x, y, z) → Three.js (x, z, -y),z 轴朝上且保持右手系。 */
function vec3(value: unknown, THREE: typeof import('three')): import('three').Vector3 {
  const [x, y, z] = triple(value)
  return new THREE.Vector3(x, z, -y)
}

function points(value: unknown): Array<[number, number, number]> {
  if (!Array.isArray(value)) return []
  return value.map((item) => triple(item))
}

function labelSprite(
  text: string,
  THREE: typeof import('three'),
  scale = 1,
  color = '#f5fbff',
): import('three').Sprite | null {
  if (!text) return null
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  canvas.width = 512
  canvas.height = 128
  // 不画底板:文字只出现在对象附近,避免大灰框破坏画面。
  ctx.font = '36px sans-serif'
  ctx.lineWidth = 7
  ctx.strokeStyle = 'rgba(5, 10, 18, 0.92)'
  ctx.strokeText(text.slice(0, 40), 12, 74)
  ctx.fillStyle = color
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
  // 编号同样不加底板,只留描边数字。
  ctx.font = 'bold 64px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.lineWidth = 8
  ctx.strokeStyle = 'rgba(5, 10, 18, 0.92)'
  ctx.strokeText(text.slice(0, 3), 64, 68)
  ctx.fillStyle = '#8be9fd'
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

/** 语义配色:曲面、梯度、方向、关键点尽量拉开色相,不靠相近青色区分。 */
function shapeColor(shape: DiagramShape, kind: string): number {
  const label = String(shape.label || '')
  if (/梯度|∇|gradient/i.test(label)) return 0xff8a3d
  if (/方向|direction|^e|^u|l\b/i.test(label)) return 0x67e8a5
  if (/路径|path|轨迹/i.test(label)) return 0xffd166
  if (kind === 'surface') return 0x3aa8d8
  if (kind === 'point') return 0xffd166
  if (kind === 'axis') return 0x94a3b8
  if (kind === 'plane') return 0xa78bfa
  return 0x4cc9f0
}

function colorHex(value: number): string {
  return `#${value.toString(16).padStart(6, '0')}`
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
  const arrowMaterial = new THREE.MeshBasicMaterial({
    color: 0x94a3b8, depthTest: false, transparent: true, opacity: 0.85,
  })
  // 右手系:数学 x 向右,y 向屏幕里(-z),z 向上(+y)。
  const axes: Array<[[number, number, number], [number, number, number], string]> = [
    [[-ex, 0, 0], [ex, 0, 0], 'x'],
    [[0, 0, ey], [0, 0, -ey], 'y'],
    [[0, z0, 0], [0, z1, 0], 'z'],
  ]
  for (const [from, to, label] of axes) {
    const start = new THREE.Vector3(...from)
    const end = new THREE.Vector3(...to)
    const geometry = new THREE.BufferGeometry().setFromPoints([start, end])
    root.add(new THREE.Line(geometry, material))
    const direction = end.clone().sub(start)
    const length = direction.length()
    if (length > 1e-6) {
      const head = Math.max(0.1, Math.min(0.4, length * 0.03))
      const cone = new THREE.Mesh(
        new THREE.ConeGeometry(head * 0.35, head, 12), arrowMaterial,
      )
      cone.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0), direction.clone().normalize(),
      )
      cone.position.copy(end).addScaledVector(direction.normalize(), -head / 2)
      root.add(cone)
    }
    const sprite = labelSprite(label, THREE, labelScale * 0.65)
    if (sprite) {
      const outward = end.clone().sub(start).normalize()
      sprite.position.copy(end).addScaledVector(outward, labelScale * 0.22)
      sprite.position.y -= labelScale * 0.08
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
      color, side: THREE.DoubleSide, transparent: true, opacity: 0.55,
      roughness: 0.6, metalness: 0.04,
    }))
    root.add(mesh)
    const wire = new THREE.LineSegments(
      new THREE.WireframeGeometry(geometry),
      new THREE.LineBasicMaterial({ color: 0x9bd8f0, transparent: true, opacity: 0.35 }),
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
  const headLength = Math.min(length * 0.22, Math.max(unit * 0.7, length * 0.12))
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(Math.max(unit * 0.16, headLength * 0.28), headLength, 12),
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
  const kind = shape.kind
  let color = new THREE.Color(shapeColor(shape, kind))
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
  if (kind === 'point') {
    material.depthTest = false
    // 点是注记,不是主体:半径只取场景尺度的一小部分,避免变成大球。
    const rawRadius = Math.abs(num(shape.r))
    const radius = Math.max(
      0.015, Math.min(rawRadius || unit * 0.28, unit * 0.42),
    )
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 16, 12), material,
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
            Math.max(unit * 0.045, 0.006), 6, false,
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
    // 圆在 3D 里是轮廓注记,不画实心圆盘,避免原点出现“盘子”。
    const radius = Math.abs(num(shape.r) || num(shape.radius) || 1)
    const ring: import('three').Vector3[] = []
    for (let i = 0; i < 64; i += 1) {
      const angle = (Math.PI * 2 * i) / 64
      ring.push(vec3([
        x + radius * Math.cos(angle),
        y + radius * Math.sin(angle),
        z,
      ], THREE))
    }
    const circle = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(ring), overlayLine,
    )
    circle.renderOrder = 5
    root.add(circle)
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
      const sprite = labelSprite(
        String(shape.label), THREE, labelScale,
        colorHex(shapeColor(shape, kind)),
      )
      if (sprite) {
        const to = triple(shape.to)
        const hasLine = ['segment', 'line', 'vector', 'axis'].includes(kind)
        const surfacePoint = kind === 'surface' && Array.isArray(shape.points)
          && shape.points.length
          ? shape.points[Math.floor(shape.points.length * 0.5)]
          : null
        const curvePoint = kind === 'curve' && Array.isArray(shape.points)
          && shape.points.length
          ? shape.points[Math.floor(shape.points.length * 0.5)]
          : null
        const anchor = hasLine
          ? vec3(to, THREE)
          : surfacePoint
            ? vec3(surfacePoint, THREE)
            : curvePoint
              ? vec3(curvePoint, THREE)
              : vec3([x, y, z], THREE)
        anchor.y += hasLine ? unit * 0.18 : unit * 0.25
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
    contextLostHandler = (event: Event) => {
      // 阻止默认行为后浏览器仍可尝试恢复;恢复不了就只显示文字提示。
      event.preventDefault()
      error.value = t('diagram.renderFail')
    }
    renderer.domElement.addEventListener('webglcontextlost', contextLostHandler)
    const root = new THREE.Group()
    scene.add(root)
    scene.add(new THREE.AmbientLight(0xffffff, 0.9))
    const light = new THREE.DirectionalLight(0xffffff, 1.2)
    light.position.set(4, 8, 6)
    scene.add(light)
    const unit = sceneUnit(props.spec.shapes)
    const labelScale = Math.max(1.6, Math.min(3.2, unit * 5))
    for (const shape of props.spec.shapes) {
      addShape(shape, THREE, root, unit, labelScale)
    }
    const shapeBounds = new THREE.Box3()
    root.traverse((object) => {
      // 标签精灵会把包围盒撑大,导致镜头退太远、主体变小;取景只算几何体。
      if ((object as { isSprite?: boolean }).isSprite) return
      if ((object as { geometry?: unknown }).geometry) {
        shapeBounds.expandByObject(object)
      }
    })
    // 三维图解先给出坐标轴,曲面和方向才有空间参照。
    addAxes(THREE, root, shapeBounds, labelScale)
    const notePositions = new Map<string, number>()
    props.spec.annotations.forEach((note, index) => {
      // 3D 里长文字直接贴图会叠在一起;用编号标记,正文放到画布下方图例。
      const sprite = markerSprite(String(index + 1), THREE, Math.max(0.6, unit * 2.2))
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
  if (renderer && contextLostHandler) {
    renderer.domElement.removeEventListener('webglcontextlost', contextLostHandler)
  }
  contextLostHandler = null
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
  max-width: 480px;
  margin: 4px auto 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-card);
}

.diagram-3d {
  position: relative;
  height: 560px;
  min-height: 340px;
  overflow: hidden;
  touch-action: none;
}

@media (max-width: 680px) {
  .diagram-3d-wrap {
    max-width: 100%;
  }

  .diagram-3d {
    height: 340px;
  }
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
