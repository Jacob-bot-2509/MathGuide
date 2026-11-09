# 公式渲染审计说明

运行方式（在项目根目录）：

```powershell
.\.venv\Scripts\python.exe scripts/audit/formula_render_audit.py
```

脚本使用后端实际附带的 KaTeX 和 Word 转换器，按公式出现次数统计，并列出受影响的题目 ID；不会将题目正文写入报告。审计结果保存在 [formula-render-audit.json](formula-render-audit.json)，基于本机当前的双语题库，数据变化后应重新运行。

## 本次扫描结果

当前扫描覆盖 262777 次公式出现、68524 个不同公式：KaTeX 剩余 52 次解析失败，Word 剩余 46 次。次数包含同一公式在不同语言和字段中的重复出现。另有 16 次 Word 公式转换成功但横线可能丢失，单独列为排版警告，不计入解析失败。Word 的 \cancel、\bcancel、\xcancel 与 \sout 映射为可编辑删除线；\cancelto 使用上方独立箭头及结果配合斜线显示，箭头的位置与原始 TeX 排版不同。

## 已核实的源数据缺损

- `numinamath:cn_k12:130-441db194ea8e`：对应 [NuminaMath-1.5](https://huggingface.co/datasets/project-numina/NuminaMath-1.5) train 第 497394 行，原题 SHA-1 前 12 位与 ID 一致。题干中集合条件的比较符及结束符在上游原文中已缺失，不能仅从渲染错误恢复。
- `numinamath:cn_k12:832-d79099b1dfcc`：对应同一数据集 train 第 344612 行，SHA-1 前 12 位与 ID 一致。上游解答本身已有截断和缺失，不能通过重新导入恢复。
- `olympiadbench:OE_TO_maths_zh_CEE:3163`：核对 [OlympiadBench](https://huggingface.co/datasets/Hothan/OlympiadBench) 对应配置、ID 3163，原始解答中的双下标写法已存在。

这些记录需要可靠的另一份原题、经复核的人工修订，或显式隔离；不能仅通过忽略解析异常或猜补字符声称修复。题库导入器已修复会误删数学不等式的 HTML 清理规则，但该修复不会反向恢复已损坏的旧数据。

复杂竖式中的局部横线、合并列和消去标记属于另一类问题：这些源公式可能有效，但当前 KaTeX 与 Word 转换器不完整支持。应实现保留结构的转换或可靠的另一渲染器，再对页面、PDF、Word 做逐项验证。
