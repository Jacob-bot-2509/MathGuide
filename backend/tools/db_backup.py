"""数据库一致性备份(等价于 `sqlite3 ... ".backup"`,而不是 `cp`)。

为什么不能用 `cp mathguide.db`:
- 库跑在 **WAL 模式**,最近的写入还在 `mathguide.db-wal` 里没回写主库,`cp` 主库
  等于丢掉最后一段数据(而且丢多少取决于别人什么时候 checkpoint,不可预期);
- 服务在跑的时候 `cp`,可能拷到"页写了一半"的中间态,恢复后 `PRAGMA integrity_check`
  会报错,或者更糟 —— 不报错但索引和表对不上。

所以这里用 `sqlite3.Connection.backup()`:它走 SQLite 自己的页拷贝协议,自动包含
WAL 里的内容,并且在源库被别的连接写入时也能得到一个**一致快照**。

用法(backend 目录下):
    python tools/db_backup.py                      # 备份到 data/backups/,保留最近 7 份
    python tools/db_backup.py --out /backup --keep 14
    python tools/db_backup.py --drill              # 备份后立刻恢复一份副本(演练,不动线上库)

退出码:0 = 成功;1 = 备份/校验/演练失败;2 = 库文件不存在。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sqlite3
import sys
import time
from pathlib import Path

# data/ 是唯一需要写的目录;默认与后端同源,避免脚本被拷到别处就找不到库
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "mathguide.db"
DEFAULT_KEEP = 7
CHECK_TABLES = ("users", "tokens", "usage", "diagnoses")


def table_counts(path: Path) -> dict[str, int]:
    """各表行数;表不存在就跳过(空库/旧库也能跑,不抛异常)。"""
    counts: dict[str, int] = {}
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return counts
    try:
        for table in CHECK_TABLES:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            except sqlite3.Error:
                continue
            counts[table] = int(row[0]) if row else 0
    except sqlite3.Error:
        return counts
    finally:
        conn.close()
    return counts


def integrity_ok(path: Path) -> bool:
    """`PRAGMA integrity_check` 是否为 ok(备份产物必须过这一关才算数)。

    文件不是数据库/中途被截断时 SQLite 直接抛 `DatabaseError`,这里一律当"不合格",
    让调用方回一句人能读懂的失败,而不是把 traceback 甩给运维。
    """
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def snapshot(source: Path, target: Path) -> None:
    """把 source 的一致性快照写到 target(含 WAL 中未回写的内容)。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source, timeout=30)
    try:
        dst = sqlite3.connect(target)
        try:
            # pages=-1:一次拷完(库只有几十 MB,分页反而慢)
            src.backup(dst, pages=-1, sleep=0.05)
        finally:
            dst.close()
    finally:
        src.close()


def prune(out_dir: Path, keep: int) -> list[Path]:
    """只保留最近 keep 份 `mg-*.db`;返回被删掉的清单(按 mtime 排序)。"""
    snapshots = sorted(out_dir.glob("mg-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed: list[Path] = []
    for stale in snapshots[keep:]:
        stale.unlink(missing_ok=True)
        removed.append(stale)
    return removed


def _human_mb(size: int) -> str:
    return f"{size / 1024 / 1024:.2f} MB"


def drill_restore(snapshot_path: Path, workdir: Path) -> tuple[bool, str]:
    """把刚做好的快照**真的恢复一次**到临时库,证明它不只是"能打开"。

    「备份产物能通过 integrity_check」和「真出事时能恢复」是两件事:恢复走的是
    `db_restore` 里那条 backup API 路径,演练它才有意义。恢复目标是一个临时文件,
    线上库一个字节都不会动。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import db_restore  # noqa: E402 与备份同目录;放在函数内导入,避免模块级循环引用

    probe = workdir / f"drill-{os.getpid()}.db"
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # db_restore 自己会打印,别混进结论
            code = db_restore.main(["--from", str(snapshot_path), "--db", str(probe),
                                    "--backup-dir", str(workdir), "--yes"])
        if code != 0:
            return False, f"db_restore 返回 {code}(快照可打开但恢复失败)"
        if not integrity_ok(probe):
            return False, "恢复出来的库没过 integrity_check"
        expected, actual = table_counts(snapshot_path), table_counts(probe)
        if expected != actual:
            return False, f"行数不一致:备份 {expected} ≠ 恢复 {actual}"
        return True, f"已恢复一份副本 · 行数一致 {actual}"
    except sqlite3.Error as exc:
        return False, f"恢复演练失败:{exc}"
    finally:
        for leftover in (probe, probe.with_name(probe.name + "-wal"),
                         probe.with_name(probe.name + "-shm")):
            leftover.unlink(missing_ok=True)



def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台
    parser = argparse.ArgumentParser(description="SQLite 一致性备份(.backup 语义)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="源库路径")
    parser.add_argument("--out", default="", help="备份目录(默认与库同级的 backups/)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="保留最近几份")
    parser.add_argument("--drill", action="store_true",
                        help="备份后立刻用 db_restore 恢复一份副本(演练,不动线上库)")
    args = parser.parse_args(argv)

    source = Path(args.db).resolve()
    out_dir = Path(args.out).resolve() if args.out else source.parent / "backups"
    if not source.is_file():
        print(f"[FAIL] 找不到库文件: {source}")
        return 2

    target = out_dir / f"mg-{time.strftime('%Y%m%d-%H%M%S')}.db"
    print(f"源库: {source}({_human_mb(source.stat().st_size)})")
    print(f"目标: {target}")
    before = table_counts(source)
    try:
        snapshot(source, target)
    except sqlite3.Error as exc:
        print(f"[FAIL] 备份失败: {exc}")
        return 1

    if not integrity_ok(target):
        print("[FAIL] 备份产物未通过 integrity_check,不要拿它做恢复")
        return 1

    after = table_counts(target)
    print(f"产物: {_human_mb(target.stat().st_size)} · integrity_check ok")
    for name, count in after.items():
        source_count = before.get(name, 0)
        arrow = "=" if source_count == count else "→"
        print(f"  {name}: {source_count} {arrow} {count}")
    if before != after:
        # 线上有人写入时源库会继续变大,这不代表备份坏了(integrity_check 才是判据);
        # 但数量**变少**要当心:说明拷到的快照比源库旧,恢复会丢这段数据。
        lost = {n: (before.get(n, 0), after.get(n, 0)) for n in before
                if after.get(n, 0) < before.get(n, 0)}
        if lost:
            print(f"[i] 备份快照比源库旧(备份期间发生了删除?): {lost};如属意外请重跑")
        else:
            print("[i] 备份期间有新写入,快照略早于当前源库(正常)")

    removed = prune(out_dir, max(1, args.keep))
    if removed:
        print(f"清理旧备份 {len(removed)} 份(保留最近 {args.keep} 份)")

    if args.drill:
        ok, detail = drill_restore(target, out_dir)
        print(("[OK] 演练: " if ok else "[FAIL] 演练: ") + detail)
        if not ok:
            return 1
    print("[OK] 备份完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
