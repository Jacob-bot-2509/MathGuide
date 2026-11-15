# 新会话交接单（HANDOFF）

> 用法：新开一个会话，把这份文件路径发给 Cline，并说"按 docs/HANDOFF.md 继续"。
> 工作区：`C:\Users\Jacap\.cline\worktrees\c1637\code`（分支 `cline/c1637`，tag `v1.27.0`）
> 最后更新：2026-11-15 ｜ 最新提交：`release: v1.27.0 发布说明与 MANIFEST`（见 `git log -1`）

## 0. 一句话任务

覆盖率已**全部收口**（146/146 达标，后端 1577 passed / 90.06%，前端 1021 条 / 97.7%）。
下一阶段的工作重心转为：**真机验证 → 部署上线**（见 `docs/DEPLOY_PLAYBOOK.md`）。
「部署前能做完」与「上服务器才能做」的完整拆分见 [`docs/DEPLOY_SPLIT_PLAN.md`](DEPLOY_SPLIT_PLAN.md)；
其中 **§1 的 13 项 + 1bis 的 4 个执行器（1.14–1.17）已全部做完**（并发闸门 / rlimit 守卫 /
单 worker 硬校验 / 25 项验收脚本 / 备份恢复脚本 / macOS CI / 前端产物检查 / 投放幂等性 /
robots / `check_llm.py` / `load_probe.py` / `proxy_check.py` / `db_backup.py --drill`），
只剩 §2 的上机项 —— 而且每项现在都有命令，上机不用再手敲。
覆盖率只需守住"不倒退"门槛（CI `--cov-fail-under=85`）。

## 1. ⚠️ 第一件事（不要跳过）

本轮结束时全量已经跑过并全绿，**基线是可信的**：

```powershell
cd C:\Users\Jacap\.cline\worktrees\c1637\code\backend
& 'D:\Works\code\.venv\Scripts\python.exe' -m pytest -q      # 期望：1577 passed，0 failed（约 90s）
```

- 改代码后再跑；若红先修红，别继续叠加改动。
- 全量超过单条命令 30 秒上限，用后台方式跑：
  `Start-Process` 重定向到 `tmp.log`，再 `Start-Sleep` + 读日志。

## 2. 当前状态（覆盖率收口后，工作树 clean）

| 项 | 数值 |
| --- | --- |
| 后端测试 | **1577 passed, 0 failed**（约 90s） |
| 后端覆盖率 | **90.06%**（16291 语句，未覆盖 1620） |
| 前端测试 | 脚本套件全过 + vitest **51 文件 / 1021 条** |
| 前端覆盖率 | **97.70%**（utils/stores/services） |
| 已达标文件 | **146 / 146**（后端 91 + 前端 55） |
| CI 矩阵 | backend 4 条（Linux 3.13 / Windows 3.13 / **macOS 3.13** / 3.14 预览）+ frontend，全绿 |
| ruff / eslint / vue-tsc | 0 违规 / 0 违规 / 0 错误 |

已达标（不要再改）：全量都达标了。逐文件的「之前→之后 / 测试文件 / 改坏验证」见
`COVERAGE_PLAN.md` §12（本轮 G2–G7）与 §11（历史批次）。

## 3. 下一步（严格按顺序）

1. **真机验证**（覆盖率覆盖不到的部分）：
   - `backend/tools/check_pdf.py` 在 Linux + chromium 上跑一次（Windows 已 `RESULT: OK`）；
   - `research_lit.py` 的真实外网下载链路（测试只做了 fake client）；
   - 语音输入、会话轮换等需要真设备/真时间的链路。
2. **部署**：按 `docs/DEPLOY_PLAYBOOK.md` 走前置三件事 → PDF 方案 A → 备份 → 安全开关 → 验收 → 回滚。
3. ~~**结构债**：`chat.py:1645` 疑似死代码~~ —— **已删除**（2026-11-14，见 `COVERAGE_PLAN.md` §12.10）。

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
- **§2 的执行器（本轮新增，见 `DEPLOY_SPLIT_PLAN.md` §1bis）**：`tools/check_llm.py`（2.5，含 `--failover`
  打坏主用验异平台接管）、`tools/load_probe.py`（2.3/2.4/2.12，长文档耗时 / 并发导出 RSS / 并发首字）、
  `tools/proxy_check.py`（2.7/2.8/2.13，证书 / HSTS / `X-Forwarded-Proto` / Cookie 三属性 / 麦克风策略 / webhook）、
  `db_backup.py --drill`（2.10，备份后立刻恢复副本）
- 工具脚本的测试**例外条款**：§4 的"不为工具脚本写测试"针对的是行覆盖凑数；这 4 个脚本的 40 条用例只钉
  **判定逻辑**（429 归类 / 百分位 / 末位采样 / Cookie 属性 / HSTS / 容灾接管），因为它们判错会让部署结论**反向**，
  比覆盖率数字危险得多。`tools/` 仍不进覆盖率分母（`pyproject.toml` omit）。


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
# 部署专项（项目 2.3/2.4/2.5/2.7/2.10/2.12/2.13;真结论必须在目标机跑）
cd backend; & 'D:\Works\code\.venv\Scripts\python.exe' tools/check_llm.py --failover
& 'D:\Works\code\.venv\Scripts\python.exe' tools/load_probe.py --long-doc 100
& 'D:\Works\code\.venv\Scripts\python.exe' tools/load_probe.py --export 2 --pid 0 --phone <号> --password <密码>
& 'D:\Works\code\.venv\Scripts\python.exe' tools/proxy_check.py --base-url https://<域名>
& 'D:\Works\code\.venv\Scripts\python.exe' tools/db_backup.py --drill
```
