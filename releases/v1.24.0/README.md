# MathGuide v1.24.0 发布附件

本目录是 v1.24.0 的可溯源附件，与仓库标签 `v1.24.0`、GitHub Release 资产一一对应。

| 文件 | 说明 |
| --- | --- |
| `MathGuide-v1.24.0-source.tar.gz` | **完整源码快照**。由 `git archive` 从代码提交 `292db2d` 生成，解压即完整可运行源码（不含 `.git`、`.env.local`、`backend/data`、`.venv`、`node_modules`、`releases/`） |
| `v1.24.0.patch` | 相对 `v1.23.0` 的完整二进制补丁（`git diff --binary`，排除 `releases/` 附件，共 52 个文件） |
| `MathGuide-v1.24.0-before-code.tar.gz` | **本次改动前的代码**。从基线 `189f033`（v1.23.0 发布提交）导出 35 个被改动文件的原版，便于对照公式渲染、知识点讲解与复习评判的改动前状态 |
| `MANIFEST.sha256` | 源码快照内逐文件 SHA-256（490 个文件） |
| `SHA256SUMS` | 本目录附件的 SHA-256 |
| `verify_manifest.py` | 跨平台清单校验脚本 |

## 校验

```bash
# 1. 校验附件本身
cd releases/v1.24.0
sha256sum -c SHA256SUMS

# 2. 解压并校验完整源码
tar -xzf MathGuide-v1.24.0-source.tar.gz
python verify_manifest.py MathGuide-v1.24.0
# 期望: checked=490 failures=0
```

注意：`MANIFEST.sha256` 按**源码包内的真实字节**生成。Windows 工作树可能被
`core.autocrlf` 转成 CRLF，不能直接拿工作树与归档清单比对；请以解压后的目录为准。

`MANIFEST.sha256` 对应代码提交 `292db2d`。
标签 `v1.24.0` 指向包含发布说明与附件的发布提交；源码快照由 `292db2d` 生成。

## 改动前代码

`MathGuide-v1.24.0-before-code.tar.gz` 的前缀为 `MathGuide-v1.24.0-before/`，
包含 `189f033`（v1.23.0 发布提交）中 35 个被改动源文件的原版：
后端文档/公式渲染、知识图谱、推荐、聊天、测试，以及前端图谱、聊天、公式渲染、
i18n 与版本文件。

未包含 `frontend/package-lock.json`（只改版本号）与本次新增文件（新增文件没有改动前版本）。

## 数据说明

题库文件 `backend/data/exercises/bilingual/all.jsonl` 被 gitignore，不在源码包内。
论文与习题数据均不随源码分发；运行前需单独投放数据文件。
知识点主要内容 `backend/knowledge_graph/data/point_notes.json` 已随源码分发。
