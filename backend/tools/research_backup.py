"""
科研语料库备份 / 恢复(按用户)。

备份内容:该用户的 SQLite 索引、原文件、向量缓存。
不包含账号本身;恢复只还原论文与项目数据。

用法(backend 目录):
    python tools/research_backup.py --uid u-13800138000 --out backup.tar.gz
    python tools/research_backup.py --uid u-13800138000 --restore backup.tar.gz
    python tools/research_backup.py --uid u-13800138000 --restore backup.tar.gz --force

安全:
- 恢复前校验 tar 成员路径,拒绝绝对路径与 `..`;
- 目标目录已存在且非空时,默认拒绝覆盖,需显式 --force;
- 恢复使用 tarfile 的 data filter(Python 3.12+),兜底再校验一次。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import research_corpus as rc  # noqa: E402


def _target(uid: str) -> Path:
    return rc.DATA_DIR / rc._safe_uid(uid)


def backup(uid: str, out: Path) -> None:
    src = _target(uid)
    if not src.exists():
        raise SystemExit(f"该用户没有科研语料: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src, arcname=".")
    print(f"已备份 {src} → {out} ({(out.stat().st_size / 1024 / 1024):.2f} MB)")


def _check_members(tar: tarfile.TarFile) -> None:
    for member in tar.getmembers():
        name = Path(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise SystemExit(f"拒绝不安全的归档成员: {member.name}")


def restore(uid: str, archive: Path, force: bool) -> None:
    if not archive.is_file():
        raise SystemExit(f"备份文件不存在: {archive}")
    target = _target(uid)
    if target.exists() and any(target.iterdir()) and not force:
        raise SystemExit(f"目标目录已有数据: {target}\n确认覆盖请加 --force")

    tmp = Path(tempfile.mkdtemp(prefix="mg-research-restore-"))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            _check_members(tar)
            try:
                tar.extractall(tmp, filter="data")  # Python 3.12+
            except TypeError:
                tar.extractall(tmp)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(target))
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    rc._indexes.pop(uid, None)
    rc._index_paths.pop(uid, None)
    print(f"已恢复 {archive} → {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="科研语料库备份 / 恢复")
    parser.add_argument("--uid", required=True, help="内部 uid(backend/data/users.json)")
    parser.add_argument("--out", help="备份输出路径(默认 research-<uid>-日期.tar.gz)")
    parser.add_argument("--restore", help="从该备份恢复")
    parser.add_argument("--force", action="store_true", help="恢复时允许覆盖现有数据")
    args = parser.parse_args()

    if args.restore:
        restore(args.uid, Path(args.restore), args.force)
        return
    out = Path(args.out) if args.out else Path(
        f"research-{rc._safe_uid(args.uid)}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz")
    backup(args.uid, out)


if __name__ == "__main__":
    main()
