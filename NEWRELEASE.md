# MathGuide v1.18.0 — 高等代数几何表示、GeoGebra 3D 隐藏内核与图解修复

发布日期：2026-11-03
发布类型：功能版本（高等代数几何表示 + 图解精度 + 3D 内核）
代码快照：`0f0d9b7`（源码包由该提交生成；标签 `v1.18.0` 指向包含发布说明与附件的发布提交）
基线版本：`v1.17.0`（`8070ed6`）

本版本把高等代数中可几何化的内容接入语义层，并继续收紧图解的表示边界：

- 模型只输出代数语义，子空间、线性映射、二次型等图形由确定性构造器生成；
- 2D 继续支持 GeoGebra 隐藏内核，3D 新增隐藏内核处理可精确构造的点、线、面、球和多边形；
- 标注贴近对象、小字号、不加省略号；3D 坐标轴只画一套；
- 3D 平面/圆缺坐标时不再默默落到原点，错图宁可不画。

## 一、高等代数几何表示

新增 `backend/linear_algebra.py`，按语义块确定性生成 DiagramSpec：

- Phase 1：实子空间（0–3 维、线性/仿射）、线性映射的核与像、行列式、线性方程组、实对称特征方向。
- Phase 2：内积空间的正交投影、正交补、Gram-Schmidt、二次型与二次曲面、双线性型。
- Phase 3：复空间与酉变换（C、C² 投影）、辛空间与辛变换（R²、R⁴ 投影）、酉/辛矩阵校验。
- Phase 4：仿射变换与仿射子空间、射影变换/无穷远线/交比、SVD/极分解/条件数。
- Phase 5：隐藏 GeoGebra 3D 内核，点、线、段、向量、平面、球、多边形由离屏内核构造，页面仍由 Three.js 渲染。

语义层只接受可几何化内容；纯符号代数（商空间、张量、PID 模等）不进入图解。

## 二、GeoGebra 3D 隐藏内核

- 新增 `frontend/src/services/geogebra3dKernel.ts`：离屏 `appName:'3d'` Applet，单例、串行、失败清理重试。
- 新增 `frontend/src/utils/geogebra3dSpec.ts`：读取 `getXML()`，转换 `point3d`、`line3d`、`segment3d`、`vector3d`、`plane3d`、球面 `quadric`、`polygon3d`。
- 新增 `frontend/src/components/diagram/GeoGebra3DKernelBlock.vue`：转换结果交给 `Diagram3D`。
- `surfacecartesian3d` 不直接给网格，参数曲面/梯度继续走表达式采样 + Three.js；`Surface` 命令主动拒绝并回退。
- GeoGebra 画布不进入页面；页面只显示 MathGuide 自己的 Three.js 场景。

## 三、2D/3D 图解修复

- 标注优先贴近表示对象，不再把整幅主体包围盒当成必须绕开的外框。
- 实心多边形登记内部包围框，标签沿多边形边缘就近摆放，不落进填充。
- 2D 标注字号 10px、形状标签 11px；3D 标签上限进一步收小。
- 注释超长直接截断，不再显示 `…`；`plainLabel` 同时清掉文本里已有的 `…` 和 `...`。
- SVG/Three 标签把常见 LaTeX 片段还原成可读符号，例如 `U^\dagger U=I` 显示为 `U† U=I`。
- 3D 坐标轴由渲染器统一生成；模型自带的 `axis` 形状与 `x/y/z`、`x轴` 注释不再重复显示。
- 3D 平面/圆必须给出中心坐标；缺坐标直接丢弃，不再默认画到原点。
- `surface3d` 必须有曲面主体；模型漏掉曲面后只剩平面/点时整图丢弃。
- 题面明确写 `z=f(x,y)` 与水平平面 `z=c` 时，按题面补回缺失的曲面与高度；多个不同高度不猜。

## 四、高等代数路由与防错图

- `酉矩阵`、`辛矩阵`、`unitary`、`symplectic` 进入线性代数语义路由。
- 高等代数语义计划失败时不再退回自由作图；错图比没图更糟。
- 2×2 酉矩阵问“复平面/单位圆/特征值/谱”时，直接从题面矩阵计算特征值，画在单位圆上并各自标注。
- 2×2 酉矩阵图明确注明“C² 保范:单位圆→单位圆”“单平面只画谱”，避免把谱图误当成完整 C² 映射。
- 仿射图按题面画三角形/正方形/平行四边形；三角形图注明“仿射不保方向,只保平行”。
- 射影图注明“射影不保平行;原图平行边交于无穷远”。

## 五、验证

- 后端：`633 passed`。
- 前端图解协议：`76/76`。
- MathText：`43/43`。
- `vue-tsc --noEmit` 通过。
- Vite 生产构建通过。
- 发布前检查：`git diff --check`、源码包清单校验。

## 六、升级说明

- 前端版本号 `1.18.0`；无数据库迁移。
- GeoGebra 内核默认关闭；设置 `MG_DIAGRAM_ENGINE=geogebra` 后启用 2D/3D 隐藏内核。
- 3D 内核只接点、线、段、向量、平面、球、多边形；参数曲面仍由旧采样器处理。
- 如 CDN 不可达，可设置 `VITE_GEOGEBRA_BASE` 指向自托管的 `deployggb.js`。

## 七、附件

本目录 `releases/v1.18.0/` 提供：

- `MathGuide-v1.18.0-source.tar.gz`：完整源码快照（由 `git archive` 从代码提交 `0f0d9b7` 生成，不含 `.git`、`.env.local`、`backend/data`、`.venv`、`node_modules`、`releases/`）；
- `v1.18.0.patch`：相对 `v1.17.0` 的完整二进制补丁；
- `MANIFEST.sha256`：源码快照内逐文件 SHA-256；
- `SHA256SUMS`：本目录附件的 SHA-256；
- `verify_manifest.py`：跨平台清单校验脚本。

## 八、校验

```bash
cd releases/v1.18.0
sha256sum -c SHA256SUMS
tar -xzf MathGuide-v1.18.0-source.tar.gz
python verify_manifest.py MathGuide-v1.18.0
# 期望：checked=<清单文件数> failures=0
```

注意：`MANIFEST.sha256` 按源码包内的真实字节生成。Windows 工作树可能被
`core.autocrlf` 转成 CRLF，不能直接拿工作树与归档清单比对；请以解压后的目录为准。

`MANIFEST.sha256` 对应代码提交 `0f0d9b7`。
标签 `v1.18.0` 指向包含发布说明与附件的发布提交；源码快照由 `0f0d9b7` 生成。
