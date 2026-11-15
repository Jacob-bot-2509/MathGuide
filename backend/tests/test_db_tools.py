"""tools/db_backup.py · db_restore.py:备份必须含 WAL、恢复必须能退回。

这两个脚本的上线价值全在"演练过"三个字上:没演练过的备份在真出事那天基本等于没有。
所以这里用临时库把整条链路跑一遍(含"数据还在 WAL 里没回写主库"这个最容易踩的点)。
"""
from __future__ import annotations

import sqlite3

from tools import db_backup, db_restore


def _make_db(path, rows: int) -> sqlite3.Connection:
    """建一个 WAL 模式的库并保持连接打开(这样新行留在 -wal,主库文件里没有)。"""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS users (uid TEXT PRIMARY KEY, doc TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, uid TEXT)")
    for index in range(rows):
        conn.execute("INSERT INTO users VALUES (?, ?)", (f"u{index}", "{}"))
        conn.execute("INSERT INTO usage (uid) VALUES (?)", (f"u{index}",))
    conn.commit()
    return conn


def _count(path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_snapshot_includes_rows_still_in_wal(tmp_path):
    src = tmp_path / "live.db"
    writer = _make_db(src, 3)  # 连接不关:3 行还在 WAL 里
    try:
        assert src.with_name("live.db-wal").exists()
        dst = tmp_path / "snap.db"
        db_backup.snapshot(src, dst)
        assert _count(dst, "users") == 3
        assert db_backup.integrity_ok(dst)
    finally:
        writer.close()


def test_backup_main_reports_and_prunes(tmp_path):
    src = tmp_path / "mathguide.db"
    writer = _make_db(src, 2)
    writer.close()
    out = tmp_path / "backups"

    assert db_backup.main(["--db", str(src), "--out", str(out), "--keep", "2"]) == 0
    snapshots = sorted(out.glob("mg-*.db"))
    assert len(snapshots) == 1

    # 造两份更早的备份,keep=2 应把它们清掉只留最新两份
    for name in ("mg-20200101-000000.db", "mg-20200102-000000.db"):
        (out / name).write_bytes(b"old")
    assert db_backup.main(["--db", str(src), "--out", str(out), "--keep", "2"]) == 0
    assert len(sorted(out.glob("mg-*.db"))) == 2


def test_backup_main_missing_db_exits_2(tmp_path):
    assert db_backup.main(["--db", str(tmp_path / "nope.db"), "--out", str(tmp_path)]) == 2


def test_restore_dry_run_does_not_touch_target(tmp_path):
    src = tmp_path / "mathguide.db"
    conn = _make_db(src, 2)
    conn.close()
    snapshot = tmp_path / "snap.db"
    db_backup.snapshot(src, snapshot)

    conn = sqlite3.connect(src)
    conn.execute("INSERT INTO users VALUES ('extra', '{}')")
    conn.commit()
    conn.close()
    assert _count(src, "users") == 3

    assert db_restore.main(["--from", str(snapshot), "--db", str(src)]) == 0
    assert _count(src, "users") == 3  # 演练不动数据


def test_restore_round_trip_rolls_data_back_and_keeps_safety_copy(tmp_path):
    src = tmp_path / "mathguide.db"
    conn = _make_db(src, 2)
    conn.close()
    snapshot = tmp_path / "snap.db"
    db_backup.snapshot(src, snapshot)

    conn = sqlite3.connect(src)
    conn.execute("INSERT INTO users VALUES ('extra', '{}')")
    conn.commit()
    conn.close()

    assert db_restore.main(["--from", str(snapshot), "--db", str(src), "--yes"]) == 0
    assert _count(src, "users") == 2
    assert db_backup.integrity_ok(src)
    safety = list((tmp_path / "backups").glob("mg-prerestore-*.db"))
    assert len(safety) == 1
    assert _count(safety[0], "users") == 3  # 安全副本保留的是"恢复前"的样子


def test_restore_refuses_corrupt_snapshot(tmp_path):
    src = tmp_path / "mathguide.db"
    conn = _make_db(src, 1)
    conn.close()
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a database")

    assert db_restore.main(["--from", str(broken), "--db", str(src), "--yes"]) == 1
    assert _count(src, "users") == 1  # 目标库没被动过


def test_restore_missing_snapshot_exits_2(tmp_path):
    src = tmp_path / "mathguide.db"
    conn = _make_db(src, 1)
    conn.close()
    assert db_restore.main(["--from", str(tmp_path / "nope.db"), "--db", str(src)]) == 2


def test_backup_drill_restores_a_copy_and_cleans_up(tmp_path):
    """--drill 的价值:把「备份能打开」升级为「备份能恢复」,而且不碰线上库。"""
    src = tmp_path / "mathguide.db"
    conn = _make_db(src, 4)
    conn.close()
    out = tmp_path / "backups"

    assert db_backup.main(["--db", str(src), "--out", str(out), "--drill"]) == 0
    assert len(list(out.glob("mg-*.db"))) == 1
    # 演练产物必须删掉,否则备份目录里会混进一个"看起来像备份"的临时库
    assert not list(out.glob("drill-*.db"))
    assert _count(src, "users") == 4


def test_backup_drill_reports_failure_on_corrupt_snapshot(tmp_path, monkeypatch):
    """快照突然读不了(磁盘/权限)时,--drill 必须报失败而不是静默通过。"""
    src = tmp_path / "mathguide.db"
    conn = _make_db(src, 1)
    conn.close()
    out = tmp_path / "backups"

    monkeypatch.setattr(db_backup, "table_counts", lambda path, _orig=db_backup.table_counts: (
        {"users": 99} if "drill-" in str(path) else _orig(path)))
    assert db_backup.main(["--db", str(src), "--out", str(out), "--drill"]) == 1

