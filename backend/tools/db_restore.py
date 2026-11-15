"""从备份快照恢复数据库(走 sqlite 的 backup API,不是覆盖文件)。

为什么不照老文档"停服务 → 覆盖三个文件 → 启动":
- 覆盖文件要求 `-wal` / `-shm` 三件一起处理,漏一个就是"恢复后数据回到更早"或
  "库打不开";三件不全时 SQLite 的恢复行为还依赖版本;
- 用 backup API 直接写进目标库,SQLite 自己处理 WAL 与事务边界 —— 目标库在服务
  运行中也是安全的(读连接要么看到旧快照,要么看到新快照,不会看到半截)。

前置动作:先把**当前库**做一份 `.backup` 安全副本(`mg-prerestore-*.db`),恢复错了可以
用同一条命令再退回去 —— 这条"可回退"比"恢复快"重要得多。

用法(backend 目录下):
    python tools/db_restore.py --from data/backups/mg-20261115-120000.db           # 演练,只报告
    python tools/db_restore.py --from data/backups/mg-20261115-120000.db --yes     # 真正恢复

退出码:0 = 成功/演练完成;1 = 校验失败或库被锁;2 = 备份文件不存在。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db_backup  # noqa: E402 同目录工具,复用快照/校验/计数的唯一实现

DEFAULT_DB = db_backup.DEFAULT_DB


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台
    parser = argparse.ArgumentParser(description="从 .backup 快照恢复 SQLite 库")
    parser.add_argument("--from", dest="source", required=True, help="备份文件路径")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="目标库路径")
    parser.add_argument("--backup-dir", default="", help="安全副本目录(默认与库同级 backups/)")
    parser.add_argument("--yes", action="store_true", help="真正执行(不加只演练)")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    target = Path(args.db).resolve()
    backup_dir = Path(args.backup_dir).resolve() if args.backup_dir else target.parent / "backups"

    if not source.is_file():
        print(f"[FAIL] 备份文件不存在: {source}")
        return 2
    if not db_backup.integrity_ok(source):
        print(f"[FAIL] 备份文件未通过 integrity_check: {source}(不要用它恢复)")
        return 1

    incoming = db_backup.table_counts(source)
    print(f"备份: {source}")
    print(f"目标: {target}({'存在' if target.is_file() else '不存在,将新建'})")
    print("备份内行数: " + ", ".join(f"{k}={v}" for k, v in incoming.items()))

    if not args.yes:
        print("[i] 演练模式:未写入任何文件。确认无误后加 --yes 执行恢复。")
        return 0

    # 1) 先把当前库做一份安全副本 —— 恢复错了还能退回
    if target.is_file():
        safety = backup_dir / f"mg-prerestore-{time.strftime('%Y%m%d-%H%M%S')}.db"
        try:
            db_backup.snapshot(target, safety)
        except sqlite3.Error as exc:
            print(f"[FAIL] 无法给当前库做安全副本,已中止: {exc}")
            return 1
        print(f"安全副本: {safety}(回退命令见末尾)")

    # 2) 用 backup API 写回目标库
    try:
        db_backup.snapshot(source, target)
    except sqlite3.Error as exc:
        print(f"[FAIL] 恢复失败: {exc}")
        print("       若提示 database is locked:先停后端服务再重试(备份 API 需要写锁)")
        return 1

    if not db_backup.integrity_ok(target):
        print("[FAIL] 恢复后的库未通过 integrity_check,请立即回退到上面的安全副本")
        return 1

    restored = db_backup.table_counts(target)
    print("恢复后行数: " + ", ".join(f"{k}={v}" for k, v in restored.items()))
    print("[OK] 恢复完成")
    if target.is_file():
        last = backup_dir.glob("mg-prerestore-*.db")
        newest = max(last, key=lambda p: p.stat().st_mtime, default=None)
        if newest is not None:
            print(f"回退命令: python tools/db_restore.py --from {newest} --yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
