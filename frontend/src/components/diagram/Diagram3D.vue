<script setup lang="ts">
/** 3D 静态图解:Three.js 场景,可旋转/缩放,不自动播放动画。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramShape, DiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import {
  placeScreenLabels,
  plainLabel,
  type ScreenLabelRequest,
} from '@/utils/diagramLabels'

const props = withDefaults(defineProps<{ spec: DiagramSpec; focused?: boolean }>(), {
  focused: false,
})
const host = ref<HTMLDivElement | null>(null)
const error = ref('')

interface LabelEntry {
  id: string
  role: 'shape' | 'note' | 'axis'
  anchor: import('three').Vector3
  sprite: import('three').Sprite
  leader?: import('three').Line
  fixed?: boolean
}

let labelEntries: LabelEntry[] = []

let renderer: import('three').WebGLRenderer | null = null
let scene: import('three').Scene | null = null
let camera: import('three').PerspectiveCamera | null = null
let controls: {
  dispose(): void
  update(): void
  addEventListener(type: string, fn: () => void): void
} | null = null
let contentSphere: { center: import('three').Vector3; radius: number } | null = null
let threeRef: typeof import('three') | null = null
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
  const measure = document.createElement('canvas').getContext('2d')
  if (!measure) return null
  measure.font = '36px sans-serif'
  let body = text.slice(0, 40)
  while (body.length > 1 && measure.measureText(body).width > 960) {
    body = body.slice(0, -1)
  }
  const textWidth = Math.ceil(measure.measureText(body).width)
  const canvas = document.createElement('canvas')
  // 画布按实际文字宽度裁切,标签占位不再固定成 512px 宽的大块。
  canvas.width = Math.max(96, Math.min(1024, textWidth + 32))
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  // 不画底板:文字只出现在对象附近,避免大灰框破坏画面。
  ctx.font = '36px sans-serif'
  ctx.lineWidth = 3
  ctx.strokeStyle = 'rgba(5, 10, 18, 0.88)'
  ctx.strokeText(body, 12, 46)
  ctx.fillStyle = color
  ctx.fillText(body, 12, 46)
  const texture = new THREE.CanvasTexture(canvas)
  const material = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthTest: false,
  })
  const sprite = new THREE.Sprite(material)
  // 标签是注记,不能压住主体;文字高度按场景尺度收小,宽度按实际字形比例。
  const worldHeight = 0.5 * scale
  sprite.scale.set(worldHeight * canvas.width / canvas.height, worldHeight, 1)
  sprite.renderOrder = 20
  return sprite
}

/** 3D 注记直接显示短文字,不再用编号和下方图例把文字甩远。 */
function annotationSprite(
  text: string,
  THREE: typeof import('three'),
  scale = 1,
  color = '#dbe4f0',
): import('three').Sprite | null {
  const body = text.trim()
  if (!body) return null
  const maxChars = 18
  const maxLines = 1
  const chars = Array.from(body)
  const lines: string[] = []
  for (let index = 0; index < chars.length && lines.length < maxLines; index += maxChars) {
    lines.push(chars.slice(index, index + maxChars).join(''))
  }
  if (!lines.length) return null
  const measure = document.createElement('canvas').getContext('2d')
  if (!measure) return null
  measure.font = '34px sans-serif'
  const textWidth = Math.max(...lines.map((line) => measure.measureText(line).width))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(96, Math.min(640, Math.ceil(textWidth) + 28))
  canvas.height = lines.length * 44 + 16
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.font = '34px sans-serif'
  ctx.lineWidth = 3
  ctx.strokeStyle = 'rgba(5, 10, 18, 0.88)'
  ctx.fillStyle = color
  lines.forEach((line, index) => {
    const baseline = 36 + index * 44
    ctx.strokeText(line, 14, baseline)
    ctx.fillText(line, 14, baseline)
  })
  const texture = new THREE.CanvasTexture(canvas)
  const material = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthTest: false,
  })
  const sprite = new THREE.Sprite(material)
  const worldHeight = 0.5 * scale
  sprite.scale.set(worldHeight * canvas.width / canvas.height, worldHeight, 1)
  sprite.renderOrder = 20
  return sprite
}

/** 注记被排到外围时用细引线指回对象;引线不计入取景包围盒。 */
function createLeaderLine(
  THREE: typeof import('three'),
  root: import('three').Object3D,
): import('three').Line {
  const geometry = new THREE.BufferGeometry()
  geometry.setFromPoints([new THREE.Vector3(), new THREE.Vector3()])
  const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({
    color: 0x94a3b8, transparent: true, opacity: 0.35, depthTest: false,
  }))
  line.renderOrder = 15
  line.visible = false
  line.userData.labelDecoration = true
  root.add(line)
  return line
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

/** 记录标签原始世界尺寸;相机动了以后按屏幕像素上限重新缩放。 */
function rememberBaseScale(sprite: import('three').Sprite): void {
  sprite.userData.baseLabelScale = {
    x: sprite.scale.x,
    y: sprite.scale.y,
  }
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
): Array<{ sprite: import('three').Sprite; anchor: import('three').Vector3 }> {
  const labels: Array<{
    sprite: import('three').Sprite
    anchor: import('three').Vector3
  }> = []
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
      const anchor = end.clone().addScaledVector(outward, labelScale * 0.22)
      anchor.y -= labelScale * 0.08
      sprite.position.copy(anchor)
      root.add(sprite)
      rememberBaseScale(sprite)
      labels.push({ sprite, anchor })
    }
  }
  return labels
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
  labels: LabelEntry[] = [],
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
    // 平面/多边形/盒体必须双面渲染:否则转到背面时整块面被剔除、直接消失。
    side: THREE.DoubleSide,
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
        plainLabel(shape.label), THREE, labelScale, '#dbe4f0',
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
        rememberBaseScale(sprite)
        labels.push({
          id: `shape-${labels.length}`,
          role: 'shape',
          anchor,
          sprite,
        })
      }
    }
  }
}

interface ScreenPoint {
  x: number
  y: number
  depth: number
  ppw: number
}

function layoutLabels(THREE: typeof import('three')): void {
  if (!camera || !renderer || !labelEntries.length) return
  const width = Math.max(1, renderer.domElement.clientWidth)
  const height = Math.max(1, renderer.domElement.clientHeight)
  if (!width || !height) return
  camera.updateMatrixWorld()
  const project = (anchor: import('three').Vector3): ScreenPoint | null => {
    const camSpace = anchor.clone().applyMatrix4(camera!.matrixWorldInverse)
    const depth = -camSpace.z
    if (depth <= 0.05) return null
    const ndc = anchor.clone().project(camera!)
    return {
      x: (ndc.x * 0.5 + 0.5) * width,
      y: (-ndc.y * 0.5 + 0.5) * height,
      depth,
      ppw: height / (2 * depth * Math.tan((camera!.fov * Math.PI / 180) / 2)),
    }
  }
  const requests: ScreenLabelRequest[] = []
  for (const entry of labelEntries) {
    const point = project(entry.anchor)
    if (!point) continue
    const base = entry.sprite.userData.baseLabelScale as
      { x: number; y: number } | undefined
    if (base) {
      const maxPx = entry.role === 'note' ? 26 : entry.role === 'axis' ? 16 : 19
      const screenHeight = base.y * point.ppw
      const factor = screenHeight > maxPx ? maxPx / screenHeight : 1
      entry.sprite.scale.set(base.x * factor, base.y * factor, 1)
    }
    requests.push({
      id: entry.id,
      anchorX: point.x,
      anchorY: point.y,
      // 用实际精灵尺寸投影,而不是固定 512px 画布,避免碰撞框虚胖。
      width: Math.max(4, entry.sprite.scale.x * point.ppw),
      height: Math.max(4, entry.sprite.scale.y * point.ppw),
      priority: entry.role === 'note' ? 3 : entry.role === 'shape' ? 2 : 4,
      fixed: entry.fixed,
      // 只避让对象自己附近的一小块,不再用整幅场景包围盒把标签推到边缘。
      avoidRect: entry.role === 'axis'
        ? null
        : { x: point.x - 8, y: point.y - 8, w: 16, h: 16 },
      avoidWeight: entry.role === 'shape' ? 2 : entry.role === 'note' ? 1.2 : 0,
    })
  }
  const placements = placeScreenLabels(requests, { width, height })
  const byId = new Map(placements.map((item) => [item.id, item]))
  const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0)
  const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1)
  for (const entry of labelEntries) {
    const placement = byId.get(entry.id)
    const point = project(entry.anchor)
    if (!placement || !point) continue
    // 排不下时宁可少一个标签,也不能让文字压在图形或其他标签上。
    const hide = (entry.role === 'shape'
      && (placement.overlapsAvoid || placement.overlapsLabel))
      || (entry.role === 'note' && placement.overlapsLabel)
    entry.sprite.visible = !hide
    const dx = (placement.centerX - point.x) / point.ppw
    const dy = -(placement.centerY - point.y) / point.ppw
    entry.sprite.position.copy(entry.anchor)
      .addScaledVector(right, dx)
      .addScaledVector(up, dy)
    if (entry.leader) {
      const distance = Math.hypot(
        placement.centerX - point.x, placement.centerY - point.y,
      )
      entry.leader.visible = !hide && distance > 4
      if (entry.leader.visible) {
        const geometry = entry.leader.geometry as import('three').BufferGeometry
        geometry.setFromPoints([entry.anchor, entry.sprite.position])
        geometry.computeBoundingSphere()
      }
    }
  }
}

function applyCameraFit(focused: boolean): void {
  if (!camera || !contentSphere || !threeRef) return
  const { center, radius } = contentSphere
  // 同时受垂直与水平视场限制:手机竖屏时不能只按高度取景,否则球会被左右裁掉。
  const vFov = (camera.fov * Math.PI) / 180
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * Math.max(0.1, camera.aspect))
  const fitFov = Math.min(vFov, hFov)
  const distance = (radius / Math.sin(fitFov / 2)) * (focused ? 1.08 : 1.15)
  const direction = new threeRef.Vector3(1, 0.65, 1.15).normalize()
  camera.position.copy(center).addScaledVector(direction, distance)
  camera.lookAt(center)
  controls?.update()
  camera.updateMatrixWorld()
  layoutLabels(threeRef)
  if (renderer && scene) renderer.render(scene, camera)
}

async function boot(): Promise<void> {
  const el = host.value
  if (!el) return
  try {
    const THREE = await import('three')
    const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
    if (disposed) return
    threeRef = THREE
    scene = new THREE.Scene()
    scene.background = null
    camera = new THREE.PerspectiveCamera(45, el.clientWidth / Math.max(1, el.clientHeight), 0.1, 200)
    camera.position.set(5.5, 4.5, 7.5)
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(el.clientWidth, Math.max(props.focused ? 1 : 340, el.clientHeight))
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
    labelEntries = []
    contentSphere = null
    // 3D 坐标轴由渲染器统一生成;旧缓存里模型自带的 axis 不再重复画。
    const geometryShapes = props.spec.shapes.filter((shape) => shape.kind !== 'axis')
    const unit = sceneUnit(geometryShapes)
    const labelScale = Math.max(1.3, Math.min(2.6, unit * 4.2))
    const shapeLabels: LabelEntry[] = []
    for (const shape of geometryShapes) {
      addShape(shape, THREE, root, unit, labelScale, shapeLabels)
    }
    labelEntries.push(...shapeLabels)
    const shapeBounds = new THREE.Box3()
    root.traverse((object) => {
      // 标签精灵和引线会把包围盒撑大,导致镜头退太远、主体变小;取景只算几何体。
      const item = object as {
        isSprite?: boolean
        userData?: { labelDecoration?: boolean }
      }
      if (item.isSprite || item.userData?.labelDecoration) return
      if ((object as { geometry?: unknown }).geometry) {
        shapeBounds.expandByObject(object)
      }
    })
    // 三维图解先给出坐标轴,曲面和方向才有空间参照。
    const axisLabels = addAxes(THREE, root, shapeBounds, labelScale)
    axisLabels.forEach((entry, index) => {
      labelEntries.push({
        id: `axis-${index}`,
        role: 'axis',
        anchor: entry.anchor,
        sprite: entry.sprite,
        fixed: true,
      })
    })
    props.spec.annotations.forEach((note, index) => {
      // 3D 说明直接用短文字贴在对象旁,不再另设编号图例。
      const text = plainLabel(note.text).trim()
      if (!text || /^[xyz]\s*轴?$/i.test(text)) return
      const sprite = annotationSprite(text, THREE, Math.max(1, unit * 2.4))
      if (!sprite) return
      const anchor = vec3([note.x, note.y, num(note.z)], THREE)
      sprite.position.copy(anchor)
      root.add(sprite)
      rememberBaseScale(sprite)
      labelEntries.push({
        id: `note-${index}`,
        role: 'note',
        anchor,
        sprite,
        leader: createLeaderLine(THREE, root),
      })
    })
    const bounds = shapeBounds.isEmpty() ? null : shapeBounds
    if (bounds) {
      const sphere = bounds.getBoundingSphere(new THREE.Sphere())
      const radius = Math.max(1, sphere.radius)
      const center = sphere.center
      contentSphere = { center: center.clone(), radius }
      camera.far = Math.max(200, radius * 20)
      camera.updateProjectionMatrix()
      controls = new OrbitControls(camera, renderer.domElement)
      controls.update()
      controls.addEventListener('change', () => {
        camera?.updateMatrixWorld()
        // 标签位置全程冻结:只在初次布局时排一次,旋转不再重算。
        renderer?.render(scene!, camera!)
      })
      applyCameraFit(Boolean(props.focused))
    } else {
      controls = new OrbitControls(camera, renderer.domElement)
      controls.update()
      controls.addEventListener('change', () => {
        camera?.updateMatrixWorld()
        // 标签位置全程冻结:只在初次布局时排一次,旋转不再重算。
        renderer?.render(scene!, camera!)
      })
    }
    camera.updateMatrixWorld()
    layoutLabels(THREE)
    renderer.render(scene, camera)
    observer = new ResizeObserver(() => {
      if (!el || !renderer || !camera) return
      const w = Math.max(1, el.clientWidth)
      const h = Math.max(props.focused ? 1 : 340, el.clientHeight)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
      camera.updateMatrixWorld()
      layoutLabels(THREE)
      renderer.render(scene!, camera)
    })
    observer.observe(el)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '3D 渲染失败'
  }
}

function dispose(): void {
  disposed = true
  labelEntries = []
  contentSphere = null
  threeRef = null
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
  <div class="diagram-3d-wrap" :class="{ 'diagram-3d-wrap--focused': focused }">
    <div ref="host" class="diagram-3d" :class="{ 'diagram-3d--focused': focused }">
      <p v-if="error" class="diagram-3d-error">{{ error }}</p>
    </div>
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

.diagram-3d-wrap--focused {
  max-width: none;
  width: 100%;
  height: 100%;
  margin: 0;
  border: 0;
  border-radius: 0;
  flex: 1;
  min-height: 0;
}

.diagram-3d {
  position: relative;
  height: 560px;
  min-height: 340px;
  overflow: hidden;
  touch-action: none;
}

.diagram-3d--focused {
  height: 100%;
  min-height: 0;
}

@media (max-width: 680px) {
  .diagram-3d-wrap {
    max-width: 100%;
  }

  .diagram-3d {
    height: 340px;
  }

  .diagram-3d--focused {
    height: 100%;
    min-height: 0;
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
</style>
