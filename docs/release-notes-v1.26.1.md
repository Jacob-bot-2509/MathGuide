# MathGuide v1.26.1 — Linux 挂起、PDF 静默失败与 CI 假绿

发布日期：2026-11-15
发布类型：缺陷修复版本（无接口路径、数据表结构、前端路由变更）
代码快照：`1176a11`（源码包由该提交生成；标签 `v1.26.1` 指向包含发布说明与附件的发布提交）
基线版本：`v1.26.0`（发布提交 `49d2243`）

v1.26.0 发出去之后，main 上又合了 3 个 PR、6 个提交。都不是新功能，而是把 v1.26.0 包里**带着的三处缺陷**修掉：

- **Linux 上后端测试无声挂起**：v1.26.0 的 ubuntu 线从来没有跑完过一次（一路挂到 GitHub 的 6 小时上限），Windows 线却始终全绿 —— 于是「CI 全绿」在 v1.26.0 上是句假话。
- **PDF 导出失败完全静默**：服务器上没有可用浏览器、或浏览器沙箱起不来时，`_html_to_pdf` 只返回 `None`，日志里查不到任何原因，要等用户点「导出」才发现。
- **开机后第一条图解读取告警被吞掉**：Windows 上 `time.monotonic()` 是开机秒数，拿 `0.0` 当「从未发送」的哨兵，会让刚开机的机器丢掉冷却窗口内的首条告警。

接口、数据表、前端路由均无变化；新增只有一个可选环境变量 `MG_EDGE_NO_SANDBOX`（默认关闭）。

## 一、Linux 挂起：一条测试给 pytest 进程自己套了 512MB 地址空间上限

根因不在产品代码，在测试：

- `tests/test_analysis_client.py::test_posix_limits_is_noop_on_windows` 直接调用 `analysis_client._posix_limits()`。这个函数在 posix 上**不是空操作**：它给**当前进程**（也就是 pytest 自己）设了 `RLIMIT_AS = 512MB` 与 `RLIMIT_CPU = 30s`，而且都是硬限制、不可回升。
- 之后 analysis 三件套（numpy / scipy / pandas / statsmodels）一导入就把地址空间顶破，再往后第一次 `Thread.start()`（症状落在 `test_auth.py` 里 starlette `TestClient` 的 portal 线程）拿不到线程栈：子线程在 `_bootstrap_inner` 里就死了，永远走不到 `_started.set()`，父线程卡死在 `_started.wait()`。
- **为什么被瞒了这么久**：Windows 没有 `resource` 模块，这个函数在 Windows 上确实是空操作 → windows 线一路绿灯；ubuntu 线又恰好没有 job 超时，于是挂到默认的 6 小时上限被静默取消，谁也没去翻日志。

修复：

- 用例改成用假的 `resource` 模块观察调用，并断言**真实 `RLIMIT_AS` 前后不变**；posix 与非 posix 两条分支都覆盖。
- `analysis_client._posix_limits` 补文档：只允许作为 `preexec_fn` 在 fork 出的 worker 子进程里跑。
- `pytest.ini` 增加 `faulthandler_timeout = 180`：日后再挂起，日志直接带全线程栈 —— 这次就是靠它一次定位到 `TestClient` portal 那一行。

结果：ubuntu 线与 windows 线都是 **1506 passed**，覆盖率 89.89%。

## 二、PDF：失败不再静默，并把「有二进制」与「真的能出 PDF」分开

修掉挂起后，被掩盖的 5 条失败才露出来（`test_doc_export.py` 四例 + `test_doc_table_render.py` 一例），全部卡在 `render_pdf_bytes()` 返回 `None`。GitHub ubuntu 镜像里 `/usr/bin/google-chrome` 是**存在**的，但 headless 打印不出 PDF —— 沙箱起不来的典型表现；旧代码把浏览器 stderr 整个丢掉，日志只剩一句「浏览器未产出 PDF」。

- `_html_to_pdf` 最多尝试四档参数：`--headless=new` / `--headless`，各自再分「不追加」与「追加兼容参数」；兼容参数（`--no-sandbox`、`--disable-dev-shm-usage`）只在 `MG_EDGE_NO_SANDBOX=1` 时启用 —— **生产渲染的是模型生成内容，沙箱必须留着**，所以开关默认关闭。
- 失败日志带最后一次浏览器 stderr 尾部；靠兼容参数才成功时会记一条 info，说明这台机器需要哪一档参数。
- 新增 `doc.pdf_render_available()`：「这台机器**真的**能打印出 PDF 吗」的探针，进程内缓存一次。
- 5 条依赖真实渲染的用例改用这个探针 skip，并写明原因：环境缺能力就 skip，不再把环境问题报成渲染回归（原来的判据是 `_find_edge()`，把「有二进制」当成了「能打印」）。
- `ci.yml` 的 Test 步骤加 `MG_EDGE_NO_SANDBOX=1`（仅测试环境）。

## 三、首个图解读取告警不再被冷却窗口吞掉

`diagram_alerts` 用 `0.0` 当「从未发送过告警」的哨兵，而 `time.monotonic()` 在 Windows 上是**开机以来的秒数**。新开机的机器或刚起来的容器里它可能远小于冷却窗口（默认 300s），于是「开机后头几分钟内的第一条告警」被静默丢弃。改用 `-inf` 哨兵（`_NEVER_SENT`），并补一条把时钟钉在开机 10 秒的回归用例。

## 四、CI：从「看着绿」变成「真的绿」

- 后端 job 加 `timeout-minutes: 20`：曾挂到 6 小时默认上限，现在 20 分钟直接判失败，不再白占 runner。
- `PYTHONUNBUFFERED=1` + `-v` + `faulthandler_timeout = 180`：挂起时日志能直接指出最后一条未完成用例与全部线程栈。
- Python 3.14 线：analysis 三件套（scipy 1.14.1 / pandas 2.2.3 / statsmodels 0.14.4）没有 cp314 wheel，pip 会退化成源码编译并因缺 OpenBLAS 直接失败 → 该线**只装主依赖与测试依赖**，覆盖率不设门槛（口径不可比）。
- 随后把它从 `experimental`（失败只作信号、不拦合并）**转为正式门禁**：先修掉它唯一一条环境性失败（缺 pandas 的 worker 用例改 `pytest.importorskip`），再摘掉标记。理由很直白 —— 一个「红着也没人管」的 job 等于没有这条线，v1.26.0 的 Linux 挂起正是这么被瞒住的。
- 现在的语义：`3.13 ubuntu` / `3.13 windows` / `3.14 ubuntu` 任一条红 = 真红；将来做 3.15 前瞻时才新增带 `experimental: true` 的矩阵项。

## 五、升级注意

- **无接口路径、数据库表结构、前端路由变更**。前端版本号 `1.26.1`，「关于」页新增 v1.26.1 条目。
- 新增环境变量 `MG_EDGE_NO_SANDBOX`（默认关闭）：只在沙箱受限的容器 / Ubuntu 23.10+ 里按需打开；公网部署请保持关闭。
- 其余环境变量与 v1.26.0 一致（`MG_EDGE_PATH` / `MG_PDF_TIMEOUT` / `MG_DAILY_LLM_CALLS` / `MG_PRINT_OPEN` 等）。
- 部署自检照旧：`python backend/tools/check_pdf.py`，结论行 `RESULT: OK`。
- Linux + chromium 的首次部署仍建议先跑自检再让用户点导出；本版只是让「跑不起来」从静默变成可定位。

## 六、发布物

附件在 GitHub Release 页（`v1.26.1`），仓库内只保留发布说明与 `MANIFEST.sha256`：

| 文件 | 说明 |
| --- | --- |
| `MathGuide-v1.26.1-source.tar.gz` | 完整源码快照，`git archive` 自 `1176a11` 生成（614 个文件，2,521,166 字节） |
| `v1.26.1.patch` | 相对 `v1.26.0`（`49d2243`）的二进制补丁（25,563 字节） |
| `MathGuide-v1.26.1-before-code.tar.gz` | 基线里被改动文件的原版（13 个文件，69,262 字节） |
| `MANIFEST.sha256` | 源码快照内逐文件 SHA-256（614 条） |
| `SHA256SUMS` | 本版附件的 SHA-256 |
| `README.md` | 附件说明与校验步骤 |
| `verify_manifest.py` | 跨平台清单校验脚本 |

## 七、合并记录

- `49d2243` v1.26.0 发布提交（基线）
- `4131c39` fix(diagram_alerts): 首个告警不再被冷却窗口吞掉（0.0 哨兵 -> -inf）
- `a83aa8d` ci: 3.14 前瞻线跳过 analysis 依赖并取消覆盖率门槛
- `8165e9d` ci: 后端 job 加超时护栏、3.14 线标为非门禁，并让挂起可定位
- `6933328` fix(tests): rlimit 用例不再污染 pytest 进程，修掉 Linux 线无声挂起
- `c131838` fix(doc): 浏览器打印失败不再静默，并区分「有二进制」与「真的能出 PDF」
- `5aefc6d` fix(ci): 3.14 线转为门禁，并修掉它唯一一条环境性失败
- `aeb2185` release: v1.26.1 版本号与关于页条目
- `1176a11` PR #15 合并提交（**代码快照**，源码包由该提交生成）
- 发布提交：v1.26.1 发布说明、`MANIFEST.sha256` 与 GitHub Release 附件

历史发布说明：v1.26.0 见 `docs/release-notes-v1.26.0.md`，更早见 `releases/`（历史目录）。

## 八、验证记录

CI（PR [#15](https://github.com/Jacob-bot-2509/MathGuide/pull/15)，run 43674845050，覆盖 `1176a11` 的全部改动）：

| 线 | 结果 |
| --- | --- |
| backend py3.13 ubuntu | 1506 passed，覆盖率 89.89%（门槛 85%），75.5s |
| backend py3.13 windows | 1506 passed，覆盖率 89.89%，100.6s |
| backend py3.14 ubuntu | 1481 passed / 2 skipped（无 analysis 依赖，1 个模块整体跳过），64.5s，**真门禁** |
| frontend node 22 | 51 文件 / 1021 条通过，覆盖率门禁通过，12.9s |

附件自检（本机构建后立即执行）：

- `SHA256SUMS`：三份产物哈希全部匹配；
- 解包后 `verify_manifest.py` → `checked=614 failures=0`。

## 九、已知限制（本版不修）

- `Linux + chromium` 仍未实机验证；本版只保证「打印不出来时说得清原因」，不保证任何发行版都能出 PDF。
- 3.14 线不带 analysis 依赖，因此 `analysis_regression` 整个模块在该线被跳过；它的覆盖只由两条 3.13 基线守着。
- PDF 导出仍没有并发闸门（见 v1.26.0 的已知限制）。
