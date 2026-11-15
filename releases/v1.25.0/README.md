# MathGuide v1.25.0 发布附件

本目录是 v1.25.0 的可溯源附件，与仓库标签 `v1.25.0`、GitHub Release 资产一一对应。

| 文件 | 说明 |
| --- | --- |
| `MathGuide-v1.25.0-source.tar.gz` | **完整源码快照**。由 `git archive` 从代码提交 `8475f4a` 生成，解压即完整可运行源码（不含 `.git`、`.env.local`、`backend/data`、`.venv`、`node_modules`、`releases/`） |
| `v1.25.0.patch` | 相对 `v1.24.0` 的完整二进制补丁（`git diff --binary`，排除 `releases/`） |
| `MathGuide-v1.25.0-before-code.tar.gz` | **本次改动前的代码**。从基线 `v1.24.0` 导出被修改文件的原版，便于对照检索、评测、公式数组与题库来源修复的改动前状态 |
| `MANIFEST.sha256` | 源码快照内逐文件 SHA-256（499 个文件） |
| `SHA256SUMS` | 本目录附件的 SHA-256 |
| `verify_manifest.py` | 跨平台清单校验脚本 |

## 校验

```bash
# 1. 校验附件本身
cd releases/v1.25.0
sha256sum -c SHA256SUMS

# 2. 解压并校验完整源码
tar -xzf MathGuide-v1.25.0-source.tar.gz
python verify_manifest.py MathGuide-v1.25.0
# 期望: checked=499 failures=0
```

`MANIFEST.sha256` 按源码包内的真实字节生成。Windows 工作树可能被
`core.autocrlf` 转成 CRLF，不能直接拿工作树与归档清单比对；请以解压后的目录为准。

`MANIFEST.sha256` 对应代码提交 `8475f4a`。
标签 `v1.25.0` 指向包含发布说明与附件的发布提交；源码快照由 `8475f4a` 生成。

## 改动前代码

`MathGuide-v1.25.0-before-code.tar.gz` 的前缀为 `MathGuide-v1.25.0-before/`，
包含基线 `v1.24.0` 中被本次修改的 31 个源文件原版，
覆盖后端检索、聊天、评测、公式渲染、题库读取、测试与前端公式/图谱渲染。

未包含 `frontend/package-lock.json`（只改版本号）与本次新增文件（新增文件没有改动前版本）。

## 数据说明

内部教材抽取、400 道正确率集、审核 PDF 与 `review_packets/` 不随源码分发；
运行前需单独投放数据文件。
