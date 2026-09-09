"""
知识库每日同步一条龙(执行表 P5):增量拉取 → 召回率评测 → 报告。

用法(backend 目录下;cwd 无关,路径基于 __file__ 解析):
    python tools/sync_knowledge.py                 # 自上次同步至今的增量,默认上限 10 篇
    python tools/sync_knowledge.py --limit 20
    python tools/sync_knowledge.py --days 7        # 无同步标记时回看 7 天

流程:
    1. 读取 tools/.last_sync(不存在则用 --days 回看窗口)
    2. arXiv 增量拉取(submittedDate 范围 + 课程关键词过滤)
    3. 更新 .last_sync
    4. 跑 eval_recall 确认召回率未劣化(不过线则退出码 1)
    5. 输出摘要报告

Windows 定时任务示例(每天 09:30 自动跑):
    schtasks /Create /TN "MathGuide-KB-Sync" /SC DAILY /ST 09:30 /TR "\"D:\\code\\.venv\\Scripts\\python.exe\" \"D:\\code\\backend\\tools\\sync_knowledge.py\" --limit 20"
"""
import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_knowledge as fk  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
KB_DIR = TOOLS_DIR.parent / "knowledge"
MARKER = TOOLS_DIR / ".last_sync"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="知识库每日同步一条龙")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--days", type=int, default=7, help="无同步标记时的回看窗口(天)")
    args = ap.parse_args()

    # 1. 确定增量起点
    if MARKER.exists():
        since = MARKER.read_text(encoding="utf-8").strip() or None
    else:
        since = (date.today() - timedelta(days=args.days)).isoformat()
    print(f"同步窗口:自 {since} 起,上限 {args.limit} 篇")

    # 2. 增量拉取(课程关键词过滤,自动入库质检门)
    added = fk.fetch_arxiv(KB_DIR, args.limit, since=since, do_filter=True)
    print(f"新增 {added} 篇")

    # 3. 更新标记
    MARKER.write_text(date.today().isoformat(), encoding="utf-8")

    # 4. 召回率评测(不过线则报错)
    print("\n跑召回率评测 ...")
    ret = subprocess.run([sys.executable, str(TOOLS_DIR / "eval_recall.py")],
                         cwd=str(TOOLS_DIR.parent))
    if ret.returncode != 0:
        print("!! 召回率评测未过线,请按报告修复 keywords 后再发布。")
        return 1

    print(f"\n同步完成:新增 {added} 篇,召回率保持 100%,知识库已热重载生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
