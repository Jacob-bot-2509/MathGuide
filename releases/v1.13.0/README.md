# MathGuide v1.13.0 发布附件

本目录是 v1.13.0 的可溯源附件，与仓库标签 `v1.13.0`、GitHub Release 资产一一对应。

| 文件 | 说明 |
| --- | --- |
| `MathGuide-v1.13.0-source.tar.gz` | **完整源码快照**。由 `git archive` 从代码提交 `56572b6` 生成，解压即完整可运行源码（不含 `.git`、`.env.local`、`backend/data`、`.venv`、`node_modules`、`releases/`） |
| `v1.13.0.patch` | 相对 `v1.12.0` 的完整二进制补丁（`git diff --binary`，排除 `releases/` 附件） |
| `MANIFEST.sha256` | 源码快照内 317 个文件的逐文件 SHA-256 |
| `SHA256SUMS` | 本目录附件的 SHA-256 |
| `verify_manifest.py` | 跨平台清单校验脚本 |

## 校验

```bash
# 1. 校验附件本身
cd releases/v1.13.0
sha256sum -c SHA256SUMS

# 2. 解压并校验完整源码
tar -xzf MathGuide-v1.13.0-source.tar.gz
python verify_manifest.py MathGuide-v1.13.0
```

注意：`MANIFEST.sha256` 按**源码包内的真实字节**生成。Windows 工作树可能被
`core.autocrlf` 转成 CRLF，不能直接拿工作树与归档清单比对；请以解压后的目录为准。

`MANIFEST.sha256` 对应代码提交 `56572b6`。
发布说明与附件在后续提交中入库；标签 `v1.13.0` 指向上述代码提交。
