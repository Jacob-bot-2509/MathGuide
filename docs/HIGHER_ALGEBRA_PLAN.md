# 高等代数几何表示层实施方案

日期：2026-11-03
关联：[可几何表示版块总表](HIGHER_ALGEBRA_VISUAL_MAP.md) · [图解不变量](DIAGRAM_INVARIANTS.md) · [GeoGebra 2D 隐藏内核](GEOGEBRA_KERNEL.md)

## 1. 目标

把高等代数中“能用几何表达”的内容做成独立表示层：

- 模型只输出代数语义，不自由手画几何；
- 后端校验基、维数、形式、变换和不变量；
- 后端确定性生成图形；
- 前端继续用现有 SVG / Three.js 渲染；
- GeoGebra 只做实数二维/三维的精确几何执行器；
- 抽象内容不硬画，直接不做或降级为结构图。

非目标：

- 不覆盖纯符号代数、纯矩阵证明、存在性定理；
- 不把若尔当标准形、λ-矩阵、PID 模、Galois 理论硬画成 3D；
- 不把复空间/R⁴ 直接冒充三维空间。
- 概率统计图示另立计划，不纳入本工程；本计划只负责高等代数可几何表示部分。

## 2. 总体架构

```
问题 / 回答段落
  ↓
线性代数分类器（版块 + 底域 + 维数 + 意图）
  ↓
语义计划（subspace / form / transform / projection）
  ↓
语义校验（基、维数、形式、不变量）
  ↓
确定性构造器
  ↓
DiagramSpec（geometry2d / geometry3d）
  ↓
DiagramSvg / Diagram3D
  ↑
可选：GeoGebra 3D 隐藏内核（仅实数三维精确构造）
```

原则：

1. 模型不直接决定点、线、面的坐标；
2. 语义层决定“画什么”，构造器决定“怎么画”；
3. GeoGebra 失败不影响主链路；
4. 任何投影必须显式标注，不冒充原空间。

## 3. 数据契约

在现有 `DiagramSpec` 上增加可选 `linear` 语义块，不新增渲染组件：

```json
{
  "type": "geometry3d",
  "title": "R^3 中由 v1,v2 张成的平面",
  "linear": {
    "domain": "real",
    "ambient": 3,
    "visual": "subspace",
    "subspace": {
      "dimension": 2,
      "kind": "linear",
      "offset": [0, 0, 0],
      "basis": [[1, 0, 0], [0, 1, 0]],
      "label": "span(v1, v2)"
    },
    "form": null,
    "transform": null,
    "projection": {
      "kind": "none",
      "note": ""
    }
  },
  "shapes": [],
  "annotations": []
}
```

### 3.1 字段

- `domain`: `real` / `complex`
- `ambient`: 2 / 3 / 4
- `visual`:
  - `subspace`
  - `linear_map`
  - `determinant`
  - `system`
  - `eigen`
  - `inner_product`
  - `quadratic_form`
  - `bilinear_form`
  - `unitary`
  - `symplectic`
  - `affine`
  - `projective`
  - `svd`
- `subspace`:
  - `dimension`
  - `kind`: `linear` / `affine`
  - `offset`: 实数或复数向量
  - `basis`: 向量数组
  - `label`
- `form`:
  - `kind`: `dot` / `symmetric` / `alternating` / `hermitian`
  - `matrix`
  - `rank`
  - `signature`
- `transform`:
  - `kind`: `linear` / `orthogonal` / `unitary` / `symplectic`
  - `matrix`
- `projection`:
  - `kind`: `none` / `complex_to_real` / `r4_to_3d` / `r4_to_2d`
  - `note`: 例如“C² 的实四维投影，仅示意”

### 3.2 复数表示

复向量/复矩阵用 `[re, im]` 对表示：

```json
[1, 2]        // 1 + 2i
[[re, im], [re, im]]
```

避免字符串解析和 `eval`。

## 4. 分类与路由

### 4.1 新增版块分类

在现有 [diagram_taxonomy.py](../backend/diagram_taxonomy.py) 的权重网之外，增加线性代数版块分类：

- `subspace`
- `linear_map`
- `determinant`
- `system`
- `eigen`
- `inner_product`
- `quadratic_form`
- `bilinear_form`
- `unitary`
- `symplectic`
- `affine`
- `projective`
- `svd`

每个版块带关键词、底域线索、环境维数线索。

### 4.2 维度与底域

- `R^2` / `\mathbb{R}^2` → real, ambient 2
- `R^3` / `\mathbb{R}^3` → real, ambient 3
- `R^4` / `\mathbb{R}^4` → real, ambient 4
- `C` / `\mathbb{C}` / 复向量空间 / 酉空间 → complex
- `子空间`、`span`、`张成`、`基`、`维数`、`秩` → 默认 real，按上下文定 ambient
- `辛` → real，偶数维，至少 2
- `酉` / `Hermitian` / `复内积` → complex

### 4.3 意图

- 明确“画/图解/直观/表示” → 优先几何；
- 纯定义、纯证明、纯计算 → 不强行画；
- 概念关系问题 → 仍可走 `tree`，但不能替代子空间几何；
- 用户要“子空间图解”时，不允许默认成思维导图。

### 4.4 路由顺序

1. 显式表示要求；
2. 版块分类；
3. 底域/维数；
4. 是否能几何化；
5. 不能几何化 → 不出图或结构图；
6. 能几何化 → 语义计划。

## 5. 语义校验

校验在构造之前执行，失败不画，回退旧链路或文字。

### 5.1 子空间

- `dimension <= ambient`
- `basis` 数量等于 `dimension`
- 基向量线性无关（高斯消元求秩）
- `kind=linear` → `offset` 必须为零
- `kind=affine` → 允许非零 offset
- 坐标有限、不过大

### 5.2 形式

- 对称：`A = A^T`
- 反对称：`A = -A^T`
- Hermitian：`A = A^*`
- 非退化：`det(A) != 0`（辛形式必须）
- 辛形式：维数偶数，反对称且非退化
- 符号差由特征值/合同标准形计算

### 5.3 变换

- 正交：`M^T M = I`
- 酉：`M^* M = I`
- 辛：`M^T J M = J`
- 一般线性：只检查矩阵尺寸和有限性

### 5.4 投影

- 复数或 R⁴ 内容必须有 `projection.note`
- 投影后维数、保留/丢失的结构写清楚
- 不能把投影图标题写成原空间结论

## 6. 确定性构造器

### 6.1 子空间

- 0 维：原点；
- 1 维：过 offset 的直线 + 一个基向量；
- 2 维：过 offset 的有限平面片 + 两个基向量；
- 3 维：整个环境空间，不画平面片，只画坐标轴和基向量；
- 线性：基向量从原点出发；
- 仿射：基向量从 offset 出发，虚线连接原点到 offset；
- 平面片大小按基向量长度和视野归一化；
- 标签：`O`、`v1`、`v2`、`span(...)`、`dim=...`、`affine: p+S`。

### 6.2 线性变换

- 变换前网格/基向量；
- 变换后网格/基向量；
- 核：被压到零的子空间；
- 像：变换后的子空间；
- 秩-零度用标签，不画额外抽象图。

### 6.3 行列式/方程组

- 行列式：平行四边形/平行六面体、面积/体积、方向；
- 方程组：二维直线族/三维平面族、交点、解集为点/线/面；
- 齐次：过原点的核；
- 非齐次：平移后的仿射子空间。

### 6.4 特征值/谱

- 实特征方向：不变直线/平面；
- 实对称：正交特征轴 + 椭球主轴；
- 复特征值：二维旋转 + 缩放，标注复结构；
- 重根/不可对角化：不硬画 3D，降级为矩阵/文字。

### 6.5 内积/正交

- 投影：点到直线/平面的垂线；
- Gram-Schmidt：逐步正交化；
- 正交补：垂直子空间；
- 正交变换：旋转/反射，保长；
- QR：正交基 + 上三角（矩阵部分只做辅助标注）。

### 6.6 二次型/双线性型

- 对称型：圆锥曲线/二次曲面、主轴、符号差；
- 反对称型：面积形式、平行四边形、辛结构；
- 退化：锥面/压扁图形；
- 正定/半正定/不定：椭球/抛物面/双曲面/锥面；
- 合同：旋转变换到标准形；
- 复杂二次曲面优先交给 GeoGebra 3D 内核。

### 6.7 复/酉

- C → R²：复平面、单位圆、旋转+伸缩；
- C² → R⁴ → 3D/2D 投影；
- Hermitian 内积：单位球、正交复方向；
- 酉变换：保范数、保内积；
- 所有投影显式标注。

### 6.8 辛

- R² 相平面：面积、辛基、各向同性直线；
- R⁴ → 3D/2D 投影：辛基、Lagrangian 平面；
- 辛变换：保面积/保 ω；
- 不伪装成普通欧氏旋转。

### 6.9 仿射/投影

- 仿射网格、平移、仿射子空间；
- 射影平面/无穷远线；
- 交比、射影变换；
- 圆锥曲线射影分类。

### 6.10 SVD/矩阵分解

- 单位圆 → 椭圆；
- 奇异值主轴；
- 极分解：旋转 + 对称拉伸；
- 条件数：椭圆扁率；
- 低秩近似：主轴截断。

## 7. 前端渲染

先复用现有渲染器，不新增复杂组件：

- `geometry2d` → `DiagramSvg`；
- `geometry3d` → `Diagram3D`；
- 平面片、直线、向量、多边形、球已有；
- 需要新增：
  - 虚线样式（仿射 offset、投影连接）；
  - 平面片透明度/边框；
  - 投影提示标签；
  - `linear` 语义块的 sanitize（不直接渲染）。

矩阵网格、交换图等示意结构不在本阶段；只做几何图。

## 8. GeoGebra 3D 内核

### 8.1 范围

只接实数三维：

- 点、线、平面、球、多边形；
- 交点、交线、切平面；
- 二次曲面；
- 实矩阵变换。

不接：

- 复空间；
- R⁴ 辛结构；
- 抽象张量/模/域；
- 高维投影语义。

### 8.2 实现

- 离屏 `appName:'3d'` Applet；
- 单独实例，不和 2D 共用；
- 白名单命令；
- `getXML()` 读取 3D 元素；
- 转成 `geometry3d`；
- 失败回退确定性构造器；
- 仍不显示 GeoGebra 3D 画布。

### 8.3 用途

- 精确平面/球/二次曲面；
- 平面交线、交点；
- 切平面；
- 实矩阵变换演示。

## 9. 分阶段交付

### Phase 1：实子空间与线性变换

- 版块分类：`subspace`、`linear_map`、`determinant`、`system`、`eigen`
- 语义 schema + 校验
- R²/R³ 子空间构造器
- 仿射子空间
- 核/像/秩-零度
- 行列式/方程组
- 实特征方向
- 测试：0/1/2/3 维、仿射、核像、退化、非法基

### Phase 2：内积与二次型

- `inner_product`、`quadratic_form`、`bilinear_form`
- 正交投影、Gram-Schmidt、正交补
- 二次型/二次曲面、符号差、正定性
- 实数三维二次曲面优先接 GeoGebra 3D
- 测试：投影、惯性定理、退化、正定/不定

### Phase 3：复/酉/辛投影

- `unitary`、`symplectic`
- C→R²、C²→R⁴→3D/2D 投影
- R⁴→3D/2D 投影
- 单位圆/球、Hermitian 内积、保范数
- 相平面、辛基、各向同性、Lagrangian
- 所有投影标注
- 测试：酉矩阵保范数、辛矩阵保 ω、投影说明

### Phase 4：仿射/投影与 SVD

- `affine`、`projective`、`svd`
- 仿射变换、射影变换、交比
- SVD/极分解/条件数/低秩近似
- 测试：仿射偏移、无穷远线、圆→椭圆

### Phase 5：3D GeoGebra 内核

- 隐藏 3D Applet
- 3D XML 转换
- 平面/球/二次曲面/交线/切平面
- 回退与超时
- 测试：真实 XML、失败回退、无 GeoGebra 画布

## 10. 验收标准

- “R³ 的子空间”不再输出 2D 图或思维导图；
- 0/1/2/3 维图形和标签正确；
- 线性子空间过原点，仿射子空间显示偏移；
- 基向量数量、维数、线性无关校验通过；
- 核/像/秩-零度几何正确；
- 二次型符号差与图形一致；
- 复/辛内容有投影标注，不冒充原空间；
- GeoGebra 3D 失败不影响正文和旧图；
- 纯代数内容不出几何图。

## 11. 风险

- **投影歧义**：复空间/R⁴ 投影必须标注，不能只画一张 3D 图就结束。
- **GeoGebra 3D 性能**：WebGL、内存、移动端；必须超时和回退。
- **二次曲面提取**：GeoGebra XML 对曲面输出需要单独探测；不行就继续表达式采样。
- **模型语义错误**：必须靠校验器拒绝非法基/维数，不交给模型自查。
- **范围膨胀**：纯代数内容明确不做，避免把系统拖成通用 CAS。

## 12. 代码落点

- `backend/diagram_taxonomy.py`：线性代数版块与线索。
- `backend/research_diagrams.py`：规划、校验、确定性构造器、验证摘要。
- `backend/linear_algebra/`：建议新增
  - `schema.py`
  - `classify.py`
  - `validate.py`
  - `builders/subspace.py`
  - `builders/forms.py`
  - `builders/transform.py`
  - `projections.py`
- `frontend/src/utils/diagramSpec.ts`：`linear` 语义块 sanitize。
- `frontend/src/components/diagram/Diagram3D.vue`：平面片、虚线、投影标注。
- `frontend/src/components/diagram/DiagramBlock.vue`：新类型路由（若后续拆分类型）。
- `frontend/src/utils/geogebra3dSpec.ts` / `services/geogebra3dKernel.ts`：Phase 5。
- 测试：
  - `backend/tests/test_linear_algebra_diagrams.py`
  - `frontend/scripts/diagram-test.ts`
  - `frontend/scripts/math-text-test.ts`（不涉及表格时保持现状）

## 13. 实施顺序建议

1. Phase 1 先做，解决“子空间画错/画成思维导图”的核心问题。
2. Phase 2 做二次型，GeoGebra 3D 可以先只作为可选加速器。
3. Phase 3 做复/辛投影，必须把“投影说明”作为一等字段。
4. Phase 4 做仿射/投影/SVD。
5. Phase 5 再接完整 3D GeoGebra 内核，不要阻塞前四阶段。
