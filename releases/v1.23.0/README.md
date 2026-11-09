# MathGuide v1.23.0 发布附件

本目录是 v1.23.0 的可溯源附件，与仓库标签 `v1.23.0`、GitHub Release 资产一一对应。

| 文件 | 说明 |
| --- | --- |
| `MathGuide-v1.23.0-source.tar.gz` | **完整源码快照**。由 `git archive` 从代码提交 `76da187` 生成，解压即完整可运行源码（不含 `.git`、`.env.local`、`backend/data`、`.venv`、`node_modules`、`releases/`） |
| `v1.23.0.patch` | 相对 `v1.22.0` 的完整二进制补丁（`git diff --binary`，排除 `releases/` 附件，共 11 个文件） |
| `MathGuide-v1.23.0-before-code.tar.gz` | **本次改动前的代码**。从基线 `5b370c1` 导出被改动文件的原版，便于对照预览/修订接口与文档弹窗的改动前状态 |
| `MANIFEST.sha256` | 源码快照内逐文件 SHA-256（474 个文件） |
| `SHA256SUMS` | 本目录附件的 SHA-256 |
| `verify_manifest.py` | 跨平台清单校验脚本 |

## 校验

```bash
# 1. 校验附件本身
cd releases/v1.23.0
sha256sum -c SHA256SUMS

# 2. 解压并校验完整源码
tar -xzf MathGuide-v1.23.0-source.tar.gz
python verify_manifest.py MathGuide-v1.23.0
# 期望: checked=474 failures=0
```

注意：`MANIFEST.sha256` 按**源码包内的真实字节**生成。Windows 工作树可能被
`core.autocrlf` 转成 CRLF，不能直接拿工作树与归档清单比对；请以解压后的目录为准。

`MANIFEST.sha256` 对应代码提交 `76da187`。
标签 `v1.23.0` 指向包含发布说明与附件的发布提交；源码快照由 `76da187` 生成。

## 改动前代码

`MathGuide-v1.23.0-before-code.tar.gz` 的前缀为 `MathGuide-v1.23.0-before/`，
包含以下文件在 `5b370c1`（本次改动前的 main）中的原版：

- 后端：`backend/docgen.py`、`backend/exercise_docgen.py`、`backend/main.py`、
  `backend/tests/test_docgen.py`
- 前端：`frontend/src/components/chat/DocModal.vue`、
  `frontend/src/services/docgenService.ts`、`frontend/src/utils/i18n.ts`
- 文档：`docs/EXERCISE_BANK_STATUS.md`

未包含 `package.json` / `package-lock.json`（只改版本号）与 `aboutContent.ts`
（只改版本记录）。

## 数据说明

题库文件 `backend/data/exercises/bilingual/all.jsonl` 与 `staging/*.jsonl`
被 gitignore，不在源码包内。运行文档生成前需单独投放数据，并设置
`MG_EXERCISE_TIERS=safe,research`。
