# GeoGebra 2D 隐藏内核

日期：2026-11-03
关联：[图解不变量](DIAGRAM_INVARIANTS.md) · [表示形式契约](REPRESENTATION_CONTRACT.md)

目标：用 GeoGebra 的构造/求交/切线能力保证数学正确，但页面仍由 MathGuide 自己的 SVG 渲染。

## 分工

```
模型 → GeoGebra 命令（后端白名单校验）
     → 离屏 GeoGebra Applet 执行
     → getXML() 读取构造结果
     → geogebraSpec.ts 转成 DiagramSpec
     → DiagramSvg 绘制
```

GeoGebra 画布不显示。隐藏 Applet 固定在屏幕外，页面只出现 `DiagramSvg`。

## 支持对象

- 点、线段、直线、射线、向量、圆、多边形/三角形。
- 函数 `f(x)=...`：取 XML 表达式，由安全表达式求值器采样。
- 切线 `Tangent`：取切点与直线系数，转成切点附近的短线段，避免切线穿过曲线。
- 交点 `Intersect`：GeoGebra 已算出点坐标，直接转点。
- 不支持的对象跳过；没有任何可渲染对象时显示图解失败，不显示 GeoGebra 画布。

## 引擎开关

```env
MG_DIAGRAM_ENGINE=geogebra
```

默认 `legacy`。GeoGebra 规划失败、命令校验失败或前端转换失败都会回退旧管线。
3D 内核只接实数三维可精确构造对象：点、线、段、向量、平面、球、多边形。
参数曲面 / 梯度 / 抛物面等仍由旧表达式采样 + Three.js 处理；`Surface` 命令会被主动拒绝并回退。
3D XML 的曲面元素 `surfacecartesian3d` 不直接给网格，因此不硬转。

## 前端加载

- 脚本地址默认 `https://www.geogebra.org/apps/deployggb.js`。
- 自托管时设置 `VITE_GEOGEBRA_BASE` 为 `deployggb.js` 的完整地址。
- Applet 离屏尺寸 640×480，单例串行复用；每次转换先清空构造。
- Applet 加载超时 25 秒；加载失败只影响当前图解，不阻塞正文。
- 转换结果再走一次 `parseDiagramSpec`，限制节点/形状/点数。

## 安全与许可

- 后端和前端都有命令白名单；禁止 `Execute`、JavaScript、文本、图片、网络、导出等。
- 命令不能包含换行、分号或超长内容。
- GeoGebra 对非商业使用免费；商业使用需按官方许可确认。页面不展示 GeoGebra 品牌。
