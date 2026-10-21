"""Explicit local connectors. The caller cannot supply paths, SQL or URLs."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import time
from pathlib import Path

from .core import FabricError, canonical, cutoff, digest, now, opaque, text


def query_sqlite(config, metric, unit, subjects, period, basis, as_of, limit):
    """Read a producer-owned facts table, retaining vintage, units and nulls.

    This is a portable demo contract, not an Altys metric implementation. Real
    Altys integration must reuse the producer's serving API and PIT semantics.
    """
    path = Path(config["path"]).resolve()
    if not path.is_file():
        raise FabricError("The configured source is unavailable.", "source_unavailable", 503)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 3
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        db.execute("PRAGMA query_only=ON")
        # Enforce a source-specific subject allowlist before the source sees a query.
        permitted = config.get("subjects")
        if permitted is not None and any(s not in permitted for s in subjects):
            raise FabricError("A requested subject is outside the source binding.")
        marks = ",".join("?" for _ in subjects)
        rows = db.execute(
            f"""WITH eligible AS (
                 SELECT subject,metric,period,basis,value,unit,available_from,
                  COUNT(*) OVER(PARTITION BY subject,metric,period,basis,available_from) AS ties,
                  ROW_NUMBER() OVER(PARTITION BY subject ORDER BY available_from DESC) AS rn
                 FROM facts WHERE metric=? AND period=? AND basis=? AND available_from<=?
                  AND subject IN ({marks})
               ) SELECT subject,metric,period,basis,value,unit,available_from,ties
                 FROM eligible WHERE rn=1 ORDER BY subject LIMIT ?""",
            (metric, period, basis, as_of, *subjects, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item.pop("ties") != 1:
                raise FabricError("Source has ambiguous vintages; read refused.", "source_invalid", 502)
            v = item["value"]
            if item["unit"] != unit or (v is not None and (type(v) not in {int, float} or not math.isfinite(v))):
                raise FabricError("Source value or unit does not match its descriptor.", "source_invalid", 502)
            if cutoff(item["available_from"]) != item["available_from"]:
                raise FabricError("Source timestamps must use canonical UTC milliseconds.", "source_invalid", 502)
            item["status"] = "unavailable" if v is None else "available"
            result.append(item)
        return result
    except sqlite3.Error as e:
        raise FabricError("Source read failed or exceeded its budget.", "source_unavailable", 503) from e
    finally:
        db.close()


def chunks(body, maximum=1800):
    """Bounded, line-addressable passages. A single long line is split explicitly."""
    parts, current, first, size = [], [], 1, 0
    for number, line in enumerate(body.splitlines(), 1):
        if current and size + len(line) + 1 > maximum:
            parts.append((first, number - 1, "\n".join(current)))
            current, size = [], 0
        if len(line) > maximum:
            for start in range(0, len(line), maximum):
                parts.append((number, number, line[start:start + maximum]))
            continue
        if not current:
            first = number
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append((first, len(body.splitlines()), "\n".join(current)))
    return [p for p in parts if p[2].strip()]


def scan_folder(config):
    root = Path(config["path"]).resolve(strict=True)
    if not root.is_dir():
        raise FabricError("The configured folder is unavailable.", "source_unavailable", 503)
    found, total = {}, 0
    deadline = time.monotonic() + 10
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            if time.monotonic() > deadline:
                raise FabricError("Folder scan exceeded its time budget; no index changes applied.")
            path = Path(directory) / name
            if path.suffix.lower() not in {".md", ".txt"} or name.startswith(".") or path.is_symlink():
                continue
            if not path.resolve().is_relative_to(root):
                raise FabricError("A source path escaped its configured root.")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise FabricError("Only regular source files are accepted.")
                raw = os.read(fd, 262145)
            finally:
                os.close(fd)
            if len(raw) > 262144:
                raise FabricError("Source file exceeds 256 KiB; no index changes applied.")
            total += len(raw)
            if total > 10 * 1024 * 1024 or len(found) >= 1000:
                raise FabricError("Folder exceeds 1,000 files or 10 MiB; no index changes applied.")
            body = raw.decode("utf-8", errors="strict")
            external_id = path.relative_to(root).as_posix()
            title = next((line.lstrip("# ").strip() for line in body.splitlines() if line.strip()), name)[:200]
            found[external_id] = {"body": body, "title": title, "version": digest(body)}
    return found


def sync_folder(store, connection_id):
    """Admin-only. Scan completely before committing a revision or any deletion."""
    with store.connect() as db:
        row = db.execute("SELECT * FROM connections WHERE id=? AND kind='folder' AND active=1", (connection_id,)).fetchone()
        if row is None:
            raise FabricError("Unknown or disabled folder connection.")
        config = json.loads(row["config"])
    try:
        found = scan_folder(config)
        with store.connect() as db:
            # Refuse an administrator changing the source binding during the scan.
            current = db.execute("SELECT * FROM connections WHERE id=? AND active=1", (connection_id,)).fetchone()
            if current is None or current["config"] != row["config"]:
                raise FabricError("Source binding changed during sync. Retry.")
            old = {r["external_id"]: dict(r) for r in db.execute(
                "SELECT * FROM documents WHERE connection_id=? AND active=1", (connection_id,))}
            changed = removed = unchanged = 0
            stamp = now()
            for ext, doc in found.items():
                if ext in old and old[ext]["version"] == doc["version"] and old[ext]["principal"] == config.get("principal", ""):
                    unchanged += 1
                    continue
                if ext in old:
                    db.execute("UPDATE documents SET active=0 WHERE id=?", (old[ext]["id"],))
                doc_id = opaque("d")
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,1)",
                           (doc_id, connection_id, ext, doc["title"], doc["version"], config.get("principal", ""), stamp))
                for i, (start, end, body) in enumerate(chunks(doc["body"])):
                    passage = opaque("p")
                    db.execute("INSERT INTO passages VALUES (?,?,?,?,?,?)", (passage, doc_id, i, body, start, end))
                    db.execute("INSERT INTO passage_fts VALUES (?,?)", (passage, body))
                changed += 1
            for ext, doc in old.items():
                if ext not in found:
                    db.execute("UPDATE documents SET active=0 WHERE id=?", (doc["id"],))
                    removed += 1
            db.execute("UPDATE connections SET last_success=?,last_error=NULL WHERE id=?", (stamp, connection_id))
            return {"connection": connection_id, "changed": changed, "removed": removed,
                    "unchanged": unchanged, "last_success": stamp}
    except (OSError, UnicodeError, FabricError) as e:
        # Do not retain source text, paths or provider exception messages in status.
        with store.connect() as db:
            db.execute("UPDATE connections SET last_error=? WHERE id=?", ("Sync failed; previous snapshot retained.", connection_id))
        if isinstance(e, FabricError):
            raise
        raise FabricError("Folder sync failed; previous snapshot retained.", "source_unavailable", 503) from e


def provision(store, config):
    """Local operator bootstrap. Configuration never arrives through MCP/HTTP."""
    store.init()
    credentials = {}
    with store.connect() as db:
        if db.execute("SELECT COUNT(*) FROM principals").fetchone()[0]:
            raise FabricError("Workspace already initialized. Use a separate state database.")
        workspace = text(config["workspace"], "workspace", 100)
        for p in config["principals"]:
            token = opaque("fabric")
            db.execute("INSERT INTO principals(id,workspace,tenant,name,token_hash) VALUES (?,?,?,?,?)",
                       (p["id"], workspace, p["tenant"], p["name"], digest(token)))
            credentials[p["id"]] = token
        for c in config["collections"]:
            db.execute("INSERT INTO collections VALUES (?,?,?,?)", (c["id"], workspace, c.get("tenant"), c["name"]))
            for g in c.get("grants", []):
                tenant, principal = g["tenant"], g.get("principal", "")
                if c.get("tenant") and tenant != c["tenant"]:
                    raise FabricError("A tenant-owned collection cannot be shared with another tenant.")
                if principal and not db.execute("SELECT 1 FROM principals WHERE id=? AND tenant=?", (principal, tenant)).fetchone():
                    raise FabricError("Grant principal must belong to the grantee tenant.")
                db.execute("INSERT INTO grants VALUES (?,?,?)", (c["id"], tenant, principal))
        for c in config["connections"]:
            kind = c["kind"]
            if kind not in {"folder", "sqlite"}:
                raise FabricError("Unsupported source kind.")
            settings = dict(c["config"])
            settings["path"] = str(Path(settings["path"]).expanduser().resolve())
            if settings.get("principal"):
                owner = db.execute("SELECT tenant FROM collections WHERE id=?", (c["collection"],)).fetchone()
                principal = db.execute("SELECT tenant FROM principals WHERE id=?", (settings["principal"],)).fetchone()
                if principal is None or owner is None or owner[0] != principal[0]:
                    raise FabricError("A restricted source requires a principal in its owning tenant.")
            db.execute("INSERT INTO connections(id,collection_id,kind,config) VALUES (?,?,?,?)",
                       (c["id"], c["collection"], kind, canonical(settings)))
            for d in c.get("descriptors", []):
                db.execute("INSERT INTO descriptors(id,connection_id,title,description,metric,unit) VALUES (?,?,?,?,?,?)",
                           (d["id"], c["id"], d["title"], d["description"], d["metric"], d["unit"]))
    return credentials
