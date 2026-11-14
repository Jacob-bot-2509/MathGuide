# 新会话交接单（HANDOFF）

> 用法：新开一个会话，把这份文件路径发给 Cline，并说"按 docs/HANDOFF.md 继续"。
> 工作区：`C:\Users\Jacap\.cline\worktrees\c1637\code`（分支 `cline/c1637`，tag `v1.26.0`）
> 最后更新：2026-11-14 ｜ 最新提交：`2a079fc`

## 0. 一句话任务

把后端/前端的测试覆盖率按 **`docs/COVERAGE_PLAN.md` 的"按文件定线"** 逐文件做到达标；
剩余 54 个文件的分组与解法见 **`docs/COVERAGE_REMAINING.md`**；部署事项见 **`docs/DEPLOY_PLAYBOOK.md`**。

## 1. ⚠️ 第一件事（不要跳过）

上一轮结束时**全量测试没跑完**就提交了 `2a079fc`（新增 `tests/test_rag_degrade.py` 7 条）。
**先验证，再继续叠加任何改动**：

```powershell
cd C:\Users\Jacap\.cline\worktrees\c1637\code\backend
& 'D:\Works\code\.venv\Scripts\python.exe' -m pytest -q      # 期望：1180+ passed，0 failed
```

- 若红：先修红，别继续做覆盖率。
- 全量跑一次约 45 秒，**超过单条命令 30 秒上限**，用后台方式跑：
  `Start-Process` 重定向到 `tmp.log`，再 `Start-Sleep` + 读日志（本会话一直是这么做的）。

## 2. 当前状态（已提交、工作树 clean）

| 项 | 数值 |
| --- | --- |
| 后端测试 | 1175 passed（+ 上一轮 7 条待验证） |
| 后端覆盖率 | **80%**（16152 语句） |
| 前端测试 | 脚本套件全过 + vitest 94 条 |
| 前端覆盖率 | 14.6%（utils/stores/services） |
| 已达标文件 | **21 / 74**（后端 17 + 前端 4） |
| ruff / eslint | 0 违规 |

已达标（不要再改）：`analysis_regression` 98 · `main` 100 · `db` 99 · `analysis_client` 94 ·
`analysis_worker` 95 · `rerank` 100 · `synthesize` 100 · `diagram_alerts` 100 · `math_table_render` 100 ·
`judges` 90 · `build` 99 · `exercise_docgen` 83 · `docgen` 81 · `linear_algebra` 85.5 ·
`rag/route` 100 · `research_urls` 93 · `doc` 80 · `cmdLink` 100 · `toast` 100 ·
`regressionChart` 100 · `workspace` 100

## 3. 下一步（严格按顺序）

**G1 剩余**：`rag/llm.py`（57.3% → 80%，缺 41 行：`69, 79, 84, 112-174, 208, 220`）
- 主体是 112–174 的流式客户端：401 / 429 / 超时 / 空响应 / `fallback` 切 backup
- 手法：假 `httpx.AsyncClient`（异步上下文 + 行迭代），断言"错误怎么映射"而不是"是否抛异常"
- 顺带确认 `rag/__init__.py` 是否已 ≥80%：`pytest tests/test_rag_degrade.py tests/test_rag_init.py -q --cov=rag --cov-report=term`（注意 `--cov=` 只能给包名 `rag`，不能给 `rag/__init__.py`）

**然后 G2 → G7**：见 `docs/COVERAGE_REMAINING.md` 的分组表（G2 五个文件零网络，最适合连做）。

## 4. 硬规则（每做完一个文件都要过）

1. 单文件覆盖率 ≥ 它所属类别的线（定线表见 `COVERAGE_PLAN.md` §2）；
2. 该文件**主要公开函数至少被调用一次**；
3. **改坏验证**：挑一条断言，把被测分支改坏 → 测试必须变红（写进提交信息）；
4. `ruff check .` 全绿 + 全量 `pytest -q` 无回归；
5. 在 `COVERAGE_PLAN.md` §11 追加一行记录（之前→之后 / 测试文件 / 改坏验证）。

**禁止**：只调用不断言的测试、为凑数给工具脚本写测试、滥用 `pragma: no cover`、
为了覆盖率改产品代码（难测是设计耦合，记成结构债）。

## 5. 环境与已踩过的坑（省你半天）

| 坑 | 现状 |
| --- | --- |
| Python 解释器 | **`D:\Works\code\.venv\Scripts\python.exe`**（3.13）。仓库里没有 `.venv` |
| numpy 曾崩 | 原为 cp314 轮子，已重装（numpy 2.2.6 / statsmodels 0.14.4 / scipy 1.14.1 / pandas 2.2.3） |
| `analysis_regression` 曾 0% | 是 `pytest.importorskip("statsmodels")` 静默跳过；CI 已补装 `requirements-analysis.txt` |
| `import main` 会写 `backend/data` | 模块级 `store.init()`；测试要先 patch 数据路径再 import（见 `tests/test_main_app.py`） |
| 控制台中文乱码 | PowerShell 默认 GBK；`tools/check_pdf.py` 已 `reconfigure(utf-8)` 并输出 ASCII `RESULT:` 行 |
| 命令行引号 | `npx`/`npm` 用 `& cmd /c "..."`；PowerShell 里 `;` 串命令 |
| 全量 pytest | 45s，超 30s 上限 → 后台跑 + 轮询 |

## 6. 部署侧（本轮已做完，勿重复）

- `docs/DEPLOY_PLAYBOOK.md`：部署唯一真源（前置三件事 / PDF 方案 A / 备份 / 安全开关 / 验收 / 回滚）
- `backend/tools/check_pdf.py`：上线前自检五项（浏览器 → 中文字体 → 真打印 → CJK 字体嵌入 → 文本层中文），
  本机 Windows + Edge 157 实测 `RESULT: OK`；**Linux chromium 尚未实测**
- 待用户执行：服务器上 `apt install -y chromium fonts-noto-cjk` → `python tools/check_pdf.py` → 眼验一份含数组公式+中文的 PDF

## 7. 常用命令

```powershell
# 全量（后台）
cd backend; Start-Process -FilePath 'D:\Works\code\.venv\Scripts\python.exe' `
  -ArgumentList '-m','pytest','-q' -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput ..\tmp.log -RedirectStandardError ..\tmp.err.log -WindowStyle Hidden
# 单模块覆盖率
cd backend; & 'D:\Works\code\.venv\Scripts\python.exe' -m pytest tests/test_<x>.py -q --cov=<module> --cov-report=term-missing
# lint
cd backend; & 'D:\Works\code\.venv\Scripts\ruff.exe' check .
cd frontend; & cmd /c "npx eslint src"
# 前端测试
cd frontend; & cmd /c "npx vitest run"
# PDF 自检
cd backend; & 'D:\Works\code\.venv\Scripts\python.exe' tools/check_pdf.py
```
