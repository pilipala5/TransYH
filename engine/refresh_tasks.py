"""Local retranslation identities; SQLite transactions survive worker interruption.

Only opaque identities, UUIDs, timestamps and lifecycle flags are stored. PDF
bytes and configuration (including credentials) exist only in memory. The
credential is an HMAC key, never part of the persisted message or cache params.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


def identity(config, base):
    source = Path(config["input"])
    before = source.stat()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = source.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Source changed while identifying task")
    source_id = config.get("sourceID")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("Missing attachment identity")
    message = json.dumps(["transyh-refresh-1", source_id, digest.hexdigest(), base,
                          config["model"].strip(), "en", "zh", "babeldoc-0.6.4"],
                         ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new((config.get("apiKey") or "local-no-key").encode(), message, hashlib.sha256).hexdigest()


@contextlib.contextmanager
def database(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "refresh-tasks.sqlite3"
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(path, 0o600)
    connection = sqlite3.connect(path, timeout=15)
    try:
        # FULL + rollback journal: a killed writer leaves either the previous
        # committed record or the new one, never a partially rewritten JSON.
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS tasks (
            identity TEXT PRIMARY KEY, token TEXT NOT NULL, version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','completed')),
            updated INTEGER NOT NULL)""")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def prepare(config, base):
    key = identity(config, base)
    with database(config["taskDir"]) as db:
        row = db.execute("SELECT token,version,status FROM tasks WHERE identity=?", (key,)).fetchone()
        if row and row[2] == "pending":
            return {"refreshToken": row[0], "taskVersion": row[1], "resumed": True}
        token = str(uuid.uuid4())
        version = f"{time.time_ns() // 1_000_000}-{token}"
        db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?)",
                   (key, token, version, "pending", int(time.time())))
        return {"refreshToken": token, "taskVersion": version, "resumed": False}


def validate(config, base):
    key = identity(config, base)
    with database(config["taskDir"]) as db:
        row = db.execute("SELECT token,status FROM tasks WHERE identity=?", (key,)).fetchone()
        if not row or row != (config.get("refreshToken"), "pending"):
            raise ValueError("Task does not match input/configuration")
    return key


def complete(config, base):
    key = identity(config, base)
    with database(config["taskDir"]) as db:
        row = db.execute("SELECT token FROM tasks WHERE identity=?", (key,)).fetchone()
        if not row or row[0] != config.get("refreshToken"):
            raise ValueError("Task completion does not match")
        db.execute("UPDATE tasks SET status='completed',updated=? WHERE identity=?",
                   (int(time.time()), key))
    return {"message": "重新翻译任务已完成。"}
