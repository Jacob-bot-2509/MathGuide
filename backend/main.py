"""
MathGuide 后端(Starlette):RAG 检索增强生成 + 科研工作台。

启动:python -m uvicorn main:app --host 127.0.0.1 --port 8000
(MG_DEMO_MODE=1 时只允许本机绑定;公网部署先设 MG_DEMO_MODE=0)

接口全表(方法 / 鉴权 / 限流 / 落盘副作用)见 backend/README.md 的「接口」一节,
并由 tests/test_api_contract.py 强制与真实路由保持一致 —— 这里只留分组概览,
不要再维护第二份逐条清单:

    /api/health                     健康检查(公开)
    /api/auth/*                     注册 / 登录 / 会话 / 登出
    /api/account/*                  导出 / 注销(级联删除)
    /api/chat/*                     流式问答 / 直观解释
    /api/research/*                 论文库、检索、文献、数据表、图解、导出
    /api/diagnosis                   掌握度诊断
    /api/recommendation              学习路径推荐
    /api/graph                       知识图谱(含导出)
    /api/profile                     学习画像与分析快照
    /api/doc/*                      综述、组卷生成与排版(PDF/Markdown/Word)
    /api/speech/math                语音 → 数学符号
    /api/stats                      用量统计(管理员)

知识库:knowledge/*.md → rag 切片索引 → 检索 → LLM(未配置则直答)。
"""
import sys

# Windows 控制台默认 GBK:模型输出含 GBK 无法编码的字符(如下标 ₀)时,
# 任何 print 都会抛 UnicodeEncodeError 打断回答链路 —— 启动即强制 UTF-8 + 行缓冲
# (行缓冲保证日志实时落盘,不会因块缓冲攒在内存里看不到)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import asyncio
import profile
from contextlib import asynccontextmanager, suppress

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import chat
import client_ip
import config
import diagnosis
import doc
import docgen
import exercise_docgen
import graph_api
import learning_analysis
import rag
import recommendation
import research_compare
import research_corpus
import research_diagrams
import research_fulltext
import research_legacy
import research_lit
import research_papers
import research_report
import research_tables
import research_vision
import retention
import store
import usage
from log import RequestIdMiddleware, get_logger
from origin_guard import OriginGuardMiddleware
from security_headers import SecurityHeadersMiddleware

# 先装载本地配置(.env.local,key 不入库),再构造 app/CORS 与数据、知识库。
# 必须早于 app 构造:MG_CORS_ORIGINS 等配置来自 .env.local。
config.load_env()
# 日志在 env 装载后再初始化:MG_LOG_LEVEL 才能生效(日志 handler 只装一次)
log = get_logger(__name__)
# 演示模式默认只允许本机;`--host 0.0.0.0` 或公网 CORS 来源会直接拒绝启动
config.assert_safe_demo_mode()
# .env.local 装载后再读限流配置(模块导入时 env 还没加载)
auth.configure_rate_limit()
chat.configure_rate_limit()
exercise_docgen.configure_rate_limit()
# 限流器与会话缓存是进程内存:多 worker 会让额度翻 N 倍、缓存各存一份。
# 演示模式只提示,公网模式直接拒绝启动(见 config.assert_single_worker)
config.assert_single_worker()
# 真实 IP 链路:MG_TRUSTED_PROXIES 是唯一开关。配成 * / 空着绑 127.0.0.1(公网)
# 都会让「10 次/分/IP」静默变形(全员一个桶或被伪造绕过),所以启动即校验。
client_ip.configure(demo=config.demo_mode(), bound=config.bound_host())


def _cors_origins() -> list[str]:
    """开发默认只放行本机前端;需要别的来源时用 MG_CORS_ORIGINS 显式列出。"""
    return config.cors_origins()


async def health(request) -> JSONResponse:
    # demo/invite 供登录页隐藏演示通道;不涉及账号或密钥
    payload = {
        "ok": True,
        "service": "mg-backend",
        "demo": config.demo_mode(),
        "invite": bool(config.invite_codes()),
    }
    # client 只在 MG_DIAG_CLIENT_IP=1 时出现(12 位哈希 + 来源),供 proxy_check.py
    # 验收真实 IP 链路;默认关闭,公开接口不长期暴露这条信息
    payload.update(client_ip.health_hint(request))
    return JSONResponse(payload)


async def stats(request) -> JSONResponse:
    """用量统计(仅管理员):总调用数 / 总字数 / 按用户 / 按模型角色"""
    auth.require_admin(request)
    # 读取/汇总 JSON 放线程池,避免大文件时阻塞事件循环
    return JSONResponse(await asyncio.to_thread(usage.summary))


routes = [
    Route("/api/health", health),
    Route("/api/auth/register", auth.register, methods=["POST"]),
    Route("/api/auth/login", auth.login, methods=["POST"]),
    Route("/api/auth/session", auth.session),
    Route("/api/auth/logout", auth.logout, methods=["POST"]),
    Route("/api/account/export", auth.export_account, methods=["POST"]),
    Route("/api/account/delete", auth.delete_account, methods=["POST"]),
    Route("/api/chat/stream", chat.chat_stream, methods=["POST"]),
    Route("/api/chat/intuition", chat.intuition, methods=["POST"]),
    Route("/api/research/docs", research_corpus.upload_doc, methods=["POST"]),
    Route("/api/research/docs", research_corpus.list_docs),
    Route("/api/research/docs", research_corpus.clear_docs, methods=["DELETE"]),
    Route("/api/research/storage", research_corpus.storage_usage),
    Route("/api/research/cache/purge", research_corpus.purge_caches, methods=["POST"]),
    Route("/api/research/diagrams/plan", research_diagrams.plan_endpoint, methods=["POST"]),
    Route("/api/research/diagrams/metrics", research_diagrams.metrics_endpoint),
    Route("/api/research/docs/{doc_id}", research_corpus.get_doc, methods=["GET"]),
    Route("/api/research/docs/{doc_id}", research_corpus.delete_doc, methods=["DELETE"]),
    Route("/api/research/docs/{doc_id}/insights", research_corpus.get_insights),
    Route("/api/research/docs/{doc_id}/insights", research_corpus.generate_insights, methods=["POST"]),
    Route("/api/research/docs/{doc_id}/progress", research_corpus.save_progress, methods=["POST"]),
    Route("/api/research/docs/{doc_id}/file", research_corpus.doc_file),
    Route("/api/research/docs/{doc_id}/text", research_corpus.doc_text),
    Route("/api/research/docs/{doc_id}/annotations", research_corpus.list_annotations),
    Route("/api/research/docs/{doc_id}/annotations", research_corpus.save_annotation, methods=["POST"]),
    Route("/api/research/docs/{doc_id}/annotations/{annotation_id}", research_corpus.delete_annotation, methods=["DELETE"]),
    Route("/api/research/papers/temp", research_papers.create_temp, methods=["POST"]),
    Route("/api/research/papers/temp-page", research_papers.create_temp_page, methods=["POST"]),
    Route("/api/research/papers/import", research_papers.import_paper, methods=["POST"]),
    Route("/api/research/papers/{doc_id}/locate", research_papers.locate, methods=["POST"]),
    Route("/api/research/papers/{doc_id}/explain-region", research_papers.explain_region, methods=["POST"]),
    Route("/api/research/papers/{doc_id}/extract-table", research_papers.extract_table, methods=["POST"]),
    Route("/api/research/history", research_papers.history_list),
    Route("/api/research/history/trash", research_papers.history_trash),
    Route("/api/research/history/{doc_id}", research_papers.history_delete, methods=["DELETE"]),
    Route("/api/research/history/{doc_id}/restore", research_papers.history_restore, methods=["POST"]),
    Route("/api/research/search", research_corpus.search_docs, methods=["POST"]),
    Route("/api/research/tree", research_corpus.tree),
    Route("/api/research/literature", research_lit.search),
    Route("/api/research/literature/related", research_lit.related),
    Route("/api/research/literature/oa", research_lit.oa_lookup),
    Route("/api/research/fulltext", research_fulltext.fulltext_lookup),
    Route("/api/research/venues", research_lit.venues_lookup),
    Route("/api/research/sources", research_lit.sources_info),
    Route("/api/research/literature/compare", research_compare.compare, methods=["POST"]),
    Route("/api/research/literature/open-pdf", research_lit.open_pdf, methods=["POST"]),
    Route("/api/research/legacy-import", research_legacy.import_archive, methods=["POST"]),
    Route("/api/research/projects", research_corpus.list_projects),
    Route("/api/research/projects", research_corpus.create_project, methods=["POST"]),
    Route("/api/research/projects/{project_id}", research_corpus.update_project, methods=["POST"]),
    Route("/api/research/projects/{project_id}", research_corpus.delete_project, methods=["DELETE"]),
    Route("/api/research/tables/import", research_tables.import_table, methods=["POST"]),
    Route("/api/research/tables", research_tables.list_tables),
    Route("/api/research/tables", research_tables.create_table, methods=["POST"]),
    Route("/api/research/tables/{table_id}", research_tables.get_table),
    Route("/api/research/tables/{table_id}", research_tables.save_table, methods=["POST"]),
    Route("/api/research/tables/{table_id}", research_tables.delete_table, methods=["DELETE"]),
    Route("/api/research/tables/{table_id}/compute", research_tables.compute_table, methods=["POST"]),
    Route("/api/research/tables/{table_id}/validate-formula", research_tables.validate_formula, methods=["POST"]),
    Route("/api/research/tables/{table_id}/suggest-topic", research_tables.suggest_topic, methods=["POST"]),
    Route("/api/research/tables/{table_id}/match-formulas", research_tables.match_formulas, methods=["POST"]),
    Route("/api/research/tables/{table_id}/stats", research_tables.stats_table, methods=["POST"]),
    Route("/api/research/tables/{table_id}/regression", research_tables.regression_table, methods=["POST"]),
    Route("/api/research/analysis/capabilities", research_tables.analysis_capabilities),
    Route("/api/research/tables/{table_id}/export", research_tables.export_table),
    Route("/api/research/report", research_report.export_report, methods=["POST"]),
    Route("/api/research/tables/{table_id}/print", research_tables.print_table, methods=["POST"]),
    Route("/api/research/formulas/extract", research_vision.extract_formulas, methods=["POST"]),
    Route("/api/research/pages/analyze", research_vision.analyze_page, methods=["POST"]),
    Route("/api/research/formulas", research_corpus.list_extracted_formulas),
    Route("/api/diagnosis", diagnosis.diagnose, methods=["POST"]),
    Route("/api/diagnosis/report", diagnosis.weak_points),
    Route("/api/recommendation", recommendation.recommend_points),
    Route("/api/graph", graph_api.graph_data),
    Route("/api/graph/export", graph_api.graph_export),
    Route("/api/profile", profile.learning_profile),
    Route("/api/profile/analysis", learning_analysis.analysis_endpoint),
    Route("/api/speech/math", chat.speech_to_math, methods=["POST"]),
    Route("/api/doc/export", doc.export_pdf, methods=["POST"]),
    Route("/api/doc/questions", docgen.questions, methods=["POST"]),
    Route("/api/doc/qa", docgen.qa_export, methods=["POST"]),
    Route("/api/doc/outline", docgen.outline, methods=["POST"]),
    Route("/api/doc/generate", docgen.generate, methods=["POST"]),
    Route("/api/doc/revise", docgen.revise, methods=["POST"]),
    Route("/api/doc/render", docgen.render, methods=["POST"]),
    Route("/api/doc/exercise/plan", exercise_docgen.plan, methods=["POST"]),
    Route("/api/doc/exercise", exercise_docgen.generate, methods=["POST"]),
    Route("/api/doc/exercise/history", exercise_docgen.history_list),
    Route("/api/doc/exercise/history/{doc_id}", exercise_docgen.history_get),
    Route("/api/doc/exercise/history/{doc_id}", exercise_docgen.history_delete, methods=["DELETE"]),
    Route("/api/doc/exercise/history/{doc_id}/confirm", exercise_docgen.history_confirm, methods=["POST"]),
    Route("/api/stats", stats),
]

@asynccontextmanager
async def _lifespan(app):
    task = asyncio.create_task(research_papers.history_retention_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = Starlette(
    lifespan=_lifespan,
    routes=routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            # 开发默认只放行本机前端(vite 5173 走代理同源,直连调试亦可用);
            # 需要其他来源时在 .env.local 配置 MG_CORS_ORIGINS,不要长期用 "*"。
            allow_origins=_cors_origins(),
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        Middleware(SecurityHeadersMiddleware),
        # 给每个请求生成 request_id,日志靠它串起同一次回答的十几条记录
        Middleware(RequestIdMiddleware),
        # 写操作的来源校验:双域共享 Cookie 时,任一子域被 XSS 不至于全站可写
        Middleware(OriginGuardMiddleware, allowed_origins=_cors_origins()),
    ],
)

# 再装载数据与知识库(演示单进程足够)
store.init()
# 旧 usage 记录只有 phone/user:启动时换成 uid 并清掉 PII(失败不阻断服务)
try:
    usage.migrate_identity(store.phone_uid_map())
except OSError as exc:
    log.warning(f"[usage] 旧用量身份迁移失败(不影响启动): {exc}")
try:
    pruned = retention.run()
    if pruned["accounts"] or pruned["usage"]:
        log.info(f"[retention] 已清理账号 {pruned['accounts']} 个、用量 {pruned['usage']} 条")
except OSError as exc:
    log.warning(f"[retention] 留存清理失败(不影响启动): {exc}")
try:
    purged = research_corpus.purge_expired_history_all()
    if purged:
        log.info(f"[retention] 已清理过期浏览历史 {purged} 条")
except OSError as exc:
    log.warning(f"[retention] 浏览历史清理失败(不影响启动): {exc}")
rag.init()
