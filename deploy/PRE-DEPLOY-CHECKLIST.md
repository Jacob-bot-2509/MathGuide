# 校服务器部署准备清单(v1.25.0)

面向 `deploy/README.md` 的补充:那份写的是「上线动作」,这份写的是
**上服务器之前还缺什么**。每条都标了仓库里的依据,可逐项打勾。

> 先明确一点:MathGuide 没有本地模型权重。它部署的是
> 「Starlette 后端 + Vue 前端 + 反向代理」,推理走阿里云百炼 / 智谱的
> OpenAI 兼容 API。所以「部署模型」实际是「部署应用 + 保住 API Key 的出口」。
> 如果学校要求全内网/本地化推理,见第 5 节末尾的改造项。

## 0. 先定基线(否则服务器上的代码 ≠ 你测过的代码)

- [ ] 当前分支 `release/v1.25.0`,但工作树是脏的:`git status` 里有 8 个已改未提交文件
      (`backend/doc.py`、`backend/graph_api.py`、`backend/tests/test_graph_api.py`、
      `frontend/src/**` 等)。**要么先提交/发新 tag,要么明确按当前 HEAD 部署**,
      否则你本地验证过的行为在服务器上可能不一致。
- [ ] 二选一取源码:
      - `git clone` + `git checkout v1.25.0`(推荐,便于回滚)
      - `releases/v1.25.0/MathGuide-v1.25.0-source.tar.gz`(对应代码提交 `8475f4a`,
        解压后先跑 `python verify_manifest.py MathGuide-v1.25.0`,期望 `failures=0`)
- [ ] 记住源码包**不含** `.env.local`、`backend/data`、`node_modules`、`frontend/dist`
      (发布包 README 也写了「运行前需单独投放数据文件」)。见第 2 节。

## 1. `backend/.env.local`:生产值缺一大半

本机这份 `.env.local` 只有模型 Key 和角色分配,**没有任何部署项**。上服务器必须补齐:

```ini
# ---- 必须改 ----
MG_DEMO_MODE=0                 # 不设=演示模式:固定验证码 123456 + 开放注册 + 游客登录
MG_INVITE_CODES=mg-2026-a      # 不设=非演示模式下注册接口直接 400 registration disabled
MG_ADMIN_PHONES=1xxxxxxxxxx    # 不设=/api/stats 无人可访问,留存清理也不保护管理员

# ---- 双域部署才需要(单域名留空)----
MG_COOKIE_DOMAIN=.example.edu.cn

# ---- 实验室共用出口 IP 时调大(默认 10 次/60s)----
MG_AUTH_RATE_MAX=60
MG_AUTH_RATE_WINDOW=60

# ---- 建议显式设定 ----
MG_GUEST_MAX=0                 # 生产建议直接关游客(默认 500)
# MG_ACCOUNT_TTL_DAYS=180      # 留存:长期未登录账号自动删
# MG_USAGE_TTL_DAYS=90
# MG_RESEARCH_MAX_UPLOAD_MB=50 # 单篇论文上限(默认 100)
# MG_RESEARCH_MAX_TOTAL_MB=500 # 每用户论文库总容量(默认 500)
# MG_RESEARCH_MAX_DOCS=100     # 每用户论文数(默认 200)
```

要点与依据:

- `config.py:31` 的 `demo_mode()` 默认值是 **1**。只绑 `127.0.0.1` 时不会报错启动,
  但反向代理把公网请求转进来后,`123456` 验证码/开放注册/游客登录全部可用 ——
  这是最危险的一处默认值。
- `auth.py:243` 非演示模式下 `invite_codes()` 为空 → 注册直接 400,学生一个都注册不上。
- `auth.py:208` 的 Cookie:`HttpOnly + SameSite=Lax + secure`(secure 由
  `X-Forwarded-Proto: https` 判定,反代必须传,nginx/Caddy 示例已传)。
- `.env.local` 权限 `chmod 600`、属主 `mathguide`;它被 `.gitignore` 的 `*.local` 排除。
- 本机这份里还有 `.env.local.example` 没列的键,别忘了原样带走:
  `MG_VISION_MODEL`、`MG_OPENALEX_API_KEY`、`MG_UNPAYWALL_EMAIL`、
  `MG_ADS_API_KEY`、`MG_LITERATURE_MAILTO`、`MG_NCBI_API_KEY`、`MG_EXERCISE_TIERS`。
- `MG_EMBED_BASE_URL` 当前指向 `ws-0zfnoih3mtuqjt7r.cn-beijing.maas.aliyuncs.com`
  (专属 MaaS 端点),不是通用公网域名 —— 校网白名单要单独放行这个域名。
- Key 建议换成为本次部署新建的子账号 + 配额上限/费用告警,别直接沿用个人主账号。

## 2. 必须单独投放的数据文件(仓库里没有,少了功能直接瘸)

`.gitignore` 把 `backend/data/` 整个忽略了,所以下面这些**不在 git、也不在源码包里**:

| 文件 | 大小 | 少了会怎样 |
| --- | --- | --- |
| `backend/data/exercises/bilingual/all.jsonl` | 20.3 MB | 题库为空,`exercise_docgen.py:100` 找不到文件 → 习题规划/生成、`/api/doc/exercise*` 不可用 |
| `backend/knowledge_graph/data/point_names.en.json` | 4.5 KB | 英文界面图谱节点名静默回退中文(`graph_api.py:27` `except OSError: return {}`) |
| `backend/knowledge_graph/data/point_notes.en.json` | 52 KB | 英文图谱注释同样静默丢失(`graph_api.py:37`) |
| `backend/data/mathguide.db`(+`-wal`/`-shm`) | 视情况 | 只有想延续账号/诊断/用量时才带;新部署留空即可 |
| `backend/data/research/` | 本机 600 MB+ | 用户上传的论文;**不要**把测试/游客数据带上线,新部署留空 |

已确认随源码走、不用另外准备的:

- `backend/knowledge/*.md`(24 篇,已跟踪)
- `backend/static/katex/`(60 个文件,含 `fonts/` 和 `math_arrays.js`)—— PDF 导出只依赖后端这一份,不需要 `node_modules`
- `backend/knowledge_graph/data/knowledge_points.csv`、`point_notes.json`
- 评测集/题库的另一半在 `backend/evaluation/data/`、`backend/exercises/`(已跟踪)

投放命令(在开发机执行,示例):

```bash
rsync -av backend/data/exercises/bilingual/all.jsonl \
      user@server:/srv/mathguide/backend/data/exercises/bilingual/
rsync -av backend/knowledge_graph/data/point_names.en.json \
      backend/knowledge_graph/data/point_notes.en.json \
      user@server:/srv/mathguide/backend/knowledge_graph/data/
```

> 顺手建议:把这两个 `.en.json` 提交进仓库,或给它们加一个投放脚本;
> 现在它们只存在于你这台机器上,换台机器构建就丢。

## 3. 服务器系统依赖(最容易漏,且不是 pip 能解决的)

- [ ] **Python 3.13**(本机 `.venv` 是 3.13.13,CI 也是 3.13;代码用了 `X | None`、
      `list[str]`,3.10 以下不行)。`.venv` 是 Windows 的,**不能拷**,必须在服务器重建:
      ```bash
      python3.13 -m venv /srv/mathguide/.venv
      /srv/mathguide/.venv/bin/pip install -r /srv/mathguide/backend/requirements.txt
      ```
      校内机器多半连不上 PyPI:配内网镜像,或本机 `pip download` 全量 wheel 后离线装。
      `pyvis` 会带 `jinja2/ipython/jsonpickle` 等未在 requirements 里 pin 的依赖,
      离线包要按 `pip freeze` 收全。
- [ ] **无头浏览器(Chromium/Edge)** —— 这是硬依赖:
      `backend/doc.py:1` 的 PDF 导出是「HTML → headless 浏览器 `--print-to-pdf`」,
      候选路径见 `doc.py:33-46`(`/usr/bin/chromium`、`/usr/bin/google-chrome` 等)。
      没装浏览器时 `_html_to_pdf()` 返回 None → `/api/doc/export` 直接 500
      (`pdf render failed`),Word/Excel 导出不受影响。
      ```bash
      sudo apt install chromium        # Debian/Ubuntu;RHEL 用 chromium-browser/edge
      ```
      两个坑:
      1. 代码**没有**传 `--no-sandbox`。容器内或禁用 user namespace 的内核上会启动失败;
         要么确认 `kernel.unprivileged_userns_clone=1`,要么在 `doc.py` 的 cmd 里补
         `--no-sandbox`(与 `NoNewPrivileges=true` 一起用时尤其要测)。
      2. Docker 下 `/dev/shm` 默认 64 MB,大文档会崩:加 `--shm-size=1g`
         或 `--disable-dev-shm-usage`。
- [ ] **中文字体**:`doc.py:243` 的字体栈是
      `'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC'`,Linux 默认都没有
      → 中文 PDF 变方框。
      ```bash
      sudo apt install fonts-noto-cjk
      ```
- [ ] **前端构建产物**:`frontend/dist` 也被 `.gitignore` 忽略。二选一:
      - 服务器装 Node 20 后 `cd frontend && npm ci && npm run build`(要能访问 npm 源)
      - 本地 `npm run build` 后 `rsync -av frontend/dist/ server:/srv/mathguide/frontend/dist/`
        (推荐,服务器不用装 Node)
- [ ] **可选组件**:
      - 回归计算 worker:独立 venv + `requirements-analysis.txt`(numpy/scipy/statsmodels),
        没有它 `/api/research/analysis/*` 返回不可用,不影响主链路
      - 只读看板:`requirements-dashboard.txt` + streamlit
      - 自检脚本 `tools/preflight.py` 只用标准库,不需要额外依赖

## 4. 反向代理与进程:我改掉的 3 个硬缺口 + 4 个要确认的点

已直接改在示例文件里:

- [x] **`deploy/nginx.conf` 缺 `client_max_body_size`** → 默认 1 MB,
      论文上传(默认上限 100 MB)在反代就被 413 掉,后端根本收不到。
      已补 `client_max_body_size 100m;`(按 `MG_RESEARCH_MAX_UPLOAD_MB` 调)。
- [x] **`deploy/mathguide.service` 的日志写不进去** → `ProtectSystem=strict`
      把整个文件系统挂成只读(含 `/var/log`),`StandardOutput=append:/var/log/...`
      会失败。已改用 systemd 的 `LogsDirectory=mathguide`,自动建目录并授权。
- [x] **embedding 缓存写不进去** → `rag/embed.py:22` 的缓存路径是
      `backend/knowledge/.embeddings.json`,原 unit 只给了 `data/` 写权限;
      已补 `ReadWritePaths=/srv/mathguide/backend/knowledge`,否则每次重启都重新
      向量化(重复计费),日志里会出现「向量缓存写盘失败」。

还要你确认:

- [ ] **真实客户端 IP**:`auth.py:98` 的限流键是 `request.client.host`。
      uvicorn 默认 `proxy_headers=True` 但只信任来自 `127.0.0.1` 的
      `X-Forwarded-For`,同机反代没问题;**一旦 nginx 与后端不同机/不同容器**,
      必须加 `--forwarded-allow-ips=<nginx IP>`,否则全站共用一个限流桶
      (表现:所有人在 60 秒内合计只能登录 30 次)。
- [ ] **SSE/超时**:后端已发 `X-Accel-Buffering: no`(`chat.py:662`),
      nginx 示例有 `proxy_buffering off` + `proxy_read_timeout 300s`。
      深度搜索 + 长回答可能超 300 s;先按 300 s 跑,压测后再调。
      Caddy 默认不缓冲,无需额外配置。
- [ ] **单 worker**:建议 `uvicorn` 单进程。多 worker 会让
      「限流器 / 内存缓存 / 启动期 retention 清理 / `research_papers` 后台保留循环」
      各跑一份,且 SQLite 写入竞争放大。要扩容先改这些,再谈 `--workers`。
- [ ] **CSP 域名**:`connect-src 'self'` 只适用于「前端与 /api 同域反代」。
      若前端和 API 分域,要同步改 CSP + `MG_CORS_ORIGINS`(见 `deploy/README.md` 第 3 节)。

## 5. 校服务器特有:网络出口、合规、内网化(最可能卡住的一节)

- [ ] **出站 HTTPS 白名单**(学校防火墙默认只放行 80/443 也可能全封)。
      按代码实际调用整理:
      - LLM:`dashscope.aliyuncs.com`(百炼)、`open.bigmodel.cn`(智谱)、
        可选 `api.deepseek.com`
      - Embedding:`ws-0zfnoih3mtuqjt7r.cn-beijing.maas.aliyuncs.com`(当前专属端点)
      - 深度搜索:`export.arxiv.org`、`api.semanticscholar.org`、`api.openalex.org`、
        `api.zbmath.org`、`api.stackexchange.com`
      - 文献增强:`api.unpaywall.org`、`api.adsabs.harvard.edu`、
        `eutils.ncbi.nlm.nih.gov`(用到才需要)
      - 知识库每日同步:`export.arxiv.org`
      → 给网络中心一张域名表,申请**出站 443 直连**;只能走代理时,
      在 systemd 里加 `Environment=HTTPS_PROXY=http://proxy:port` +
      `NO_PROXY=127.0.0.1,localhost`(httpx 默认 `trust_env=True`,会读代理变量)。
- [ ] **入站**:只开 80/443;`8000` 只绑 `127.0.0.1`,不要放公网。
      校域名解析、TLS 证书(Let's Encrypt 需 80 验证,校内常由信息办签发)提前申请。
- [ ] **个人信息合规**:注册用手机号 + PBKDF2 密码哈希;`data/` 存
      users/tokens(仅 SHA-256)/usage(仅 uid)/diagnoses。上线前应准备:
      数据用途与留存期说明(建议设 `MG_ACCOUNT_TTL_DAYS`/`MG_USAGE_TTL_DAYS`)、
      注销入口(`/api/account/delete` 已级联删)、导出入口(`/api/account/export` 已有)、
      第三方模型厂商的数据处理条款(百炼/智谱控制台的「数据不用于训练」开关 + DPA)。
      若学校要求「生成内容可审计」,目前没有正文日志,需要另加(别直接开 debug 日志)。
- [ ] **若要全内网/本地化推理**(校方常提的要求):不用改业务代码,
      把 `MG_ALIYUN_BASE_URL`/`MG_ZHIPU_BASE_URL`/`MG_EMBED_BASE_URL` 指向校内
      vLLM / Ollama / Xinference 的 OpenAI 兼容端点,并把 `MG_ROLE_*` 的模型名
      换成实际部署的模型;同时确认该模型支持 tool/JSON 输出与长上下文
      (综述、精排、图解校验都依赖结构化 JSON)。这属于「换后端」而非「部署现成包」,
      要单独排期压测。

## 6. 上线验收(按顺序打勾,别只看首页能开)

```bash
# 1. 演示模式必须已关:demo=false, invite=true
curl -s https://mg.example.edu.cn/api/health
# {"ok":true,"service":"mg-backend","demo":false,"invite":true}

# 2. 经反代注册(要邀请码)→ 登录 → 拿 token
curl -s -X POST https://mg.example.edu.cn/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"phone":"13800138000","password":"test123456","invite":"mg-2026-a"}'

# 3. SSE 不缓冲:应逐帧吐出、最后有 [DONE]
curl -N -X POST https://mg.example.edu.cn/api/chat/stream \
     -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
     -d '{"prompt":"什么是泰勒展开?"}'
```

- [ ] 浏览器:`https://…` 证书有效、HSTS 存在、控制台无 CSP violation
- [ ] 注册必须填邀请码;`{"method":"code","phone":"...","code":"123456"}` 返回 400
- [ ] **大文件上传经反代成功**:传一个 10~50 MB PDF 到科研库
      (这一步专门验证第 4 节的 `client_max_body_size`)
- [ ] **PDF 导出**:导一份中文文档,确认不是方框、公式正常
      (验证 Chromium + `fonts-noto-cjk`)
- [ ] **英文图谱**:切到英文界面看知识图谱节点名是否英文
      (验证 `point_names.en.json` 已投放)
- [ ] 管理员账号访问 `/api/stats` 返回统计(验证 `MG_ADMIN_PHONES`)
- [ ] 重启服务后:账号仍能登录、`backend/data/mathguide.db` 有更新、
      日志里**没有**「向量缓存写盘失败」、没有 500
- [ ] 日志轮转:`logrotate -d /etc/logrotate.d/mathguide` 无报错
      (`copytruncate` 已配,和 systemd 直接写文件兼容)
- [ ] 一键冒烟:`python backend/tools/preflight.py`(已支持环境变量覆盖,
      见下),生产用法:
      ```bash
      MG_PREFLIGHT_BASE=https://mg.example.edu.cn \
      MG_PREFLIGHT_FRONTEND=https://mg.example.edu.cn \
      MG_PREFLIGHT_PHONE=13800138000 \
      MG_PREFLIGHT_PASSWORD=test123456 \
      MG_PREFLIGHT_REQUIRE_PROD=1 \
      /srv/mathguide/.venv/bin/python tools/preflight.py
      ```

## 7. 备份、回滚、容量、监控

- **备份**:
  ```bash
  # 方式一:在线备份(服务不用停;WAL 模式下也不会拷到半截)
  sqlite3 backend/data/mathguide.db ".backup '/backup/mathguide.db'"

  # 方式二:停服务后整目录快照(含用户论文 research/)
  systemctl stop mathguide
  rsync -a backend/data/ /backup/data-$(date +%F)/
  systemctl start mathguide
  ```
  `data/` 是唯一可写目录,备份它 + `.env.local`(加密)+ 部署版本号即可。
  单用户论文库还可用 `tools/research_backup.py --uid u-xxx --out x.tar.gz` 导出。
  仓库建议 restic/borg 加密,并**做一次恢复演练**(`--restore`),否则备份等于没有。
- **回滚**:保留上一版 `/srv/mathguide-<ver>/` + 各自 venv,systemd 改
  `WorkingDirectory`/`ExecStart` 再 `daemon-reload`。SQLite 建表是增量且旧 JSON
  只导入一次,回滚旧代码前先备份 `data/`。
- **容量**:默认每用户论文总容量 500 MB(`research_corpus.py:97`)、单篇 100 MB、
  200 篇上限。按 `人数 × 500MB` 规划磁盘,再留日志与备份空间。
  内存:PDF 导出会拉起一个 Chromium(峰值数百 MB),并发导出要限流
  (目前只有登录用户 + 通用聊天限流,没有针对导出的并发保护)。
- **监控**:`/api/health` 做探针;告警盯日志关键字
  `Traceback|向量缓存写盘失败|retention|Chromium|print-to-pdf`;
  可选用 `MG_DIAGRAM_ALERT_WEBHOOK` 收图解失败聚合告警。

## 8. 建议的上线顺序

1. 提交/打 tag,锁定部署提交(第 0 节)
2. 服务器建用户 `mathguide`、建 `/srv/mathguide`、Python 3.13 venv、装依赖
3. 传源码 + 第 2 节数据文件 + `frontend/dist` + `.env.local`(600)
4. 本机 `systemctl start`,只绑 127.0.0.1,`curl /api/health` 确认 `demo=false`
5. 配反代(证书/DNS/CSP),跑第 6 节验收
6. 开 HSTS(确认 HTTPS 稳定之后)、挂监控与备份定时任务
7. 发邀请码给第一批试用,观察 `/api/stats` 与日志

## 9. 需要你拍板的 4 件事

1. **单域还是双域**?`learn.` / `research.` 双域才需要 `MG_COOKIE_DOMAIN`;
   单域更简单,前端本来就有工作区切换。
2. **域名与证书谁给**?校信息办域名审批 + 证书签发通常要 1~2 周,是最长的前置。
3. **是否要求全内网推理**?要的话第 5 节末尾的改造与压测要单独立项。
4. **首批人数与留存期**?决定 `MG_RESEARCH_MAX_*`、`MG_ACCOUNT_TTL_DAYS`、
   磁盘和限流阈值。
