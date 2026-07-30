"""Persistence family — P10 candidates.

- sqlite-store: python stdlib sqlite3 single-row blob store (real local DB).
- pouchdb-store: PouchDB (npm) document store, driven over stdio.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, VENVS  # noqa: E402


class SqliteStore(Candidate):
    name = "sqlite-store"
    stages = {"persistence"}

    def available(self):
        return True, ""

    def _connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS kv (id TEXT PRIMARY KEY, blob TEXT)")
        return conn

    def store_probe(self, action: str, payload: dict) -> dict:
        data_dir = Path(tempfile.mkdtemp(prefix=f"sqlite-{action}-"))
        db_path = data_dir / "store.db"
        try:
            if action == "write_read":
                n = payload.get("n", 50)
                docs = payload.get("docsPerWrite", 40)
                conn = self._connect(db_path)
                timings = []
                for i in range(n):
                    blob = json.dumps({"documents": [
                        {"id": f"doc-{i}-{j}"} for j in range(docs)]})
                    started = time.monotonic()
                    conn.execute("REPLACE INTO kv (id, blob) VALUES ('workspace', ?)", (blob,))
                    conn.commit()
                    timings.append((time.monotonic() - started) * 1000)
                conn.close()
                timings.sort()
                return {"ok": True, "p50_ms": timings[len(timings) // 2],
                        "p95_ms": timings[int(len(timings) * 0.95)],
                        "documents": docs}
            if action == "concurrent":
                writers = payload.get("writers", ["A", "B"])
                ops = payload.get("ops", 20)
                conn = self._connect(db_path)
                errors = []

                def worker(tag):
                    c = self._connect(db_path)
                    for i in range(ops):
                        try:
                            c.execute("INSERT INTO kv (id, blob) VALUES (?, '{}')",
                                      (f"doc-{tag}-{i}",))
                            c.commit()
                        except Exception as exc:
                            errors.append(str(exc))
                    c.close()
                threads = [threading.Thread(target=worker, args=(t,)) for t in writers]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                surviving = conn.execute("SELECT COUNT(*) FROM kv WHERE id != 'workspace'").fetchone()[0]
                conn.close()
                expected = len(writers) * ops
                return {"ok": True, "expected": expected, "surviving": surviving,
                        "lost": expected - surviving, "errors": len(errors)}
            if action == "atomicity":
                writes = payload.get("writes", 150)
                conn = self._connect(db_path)
                conn.execute("REPLACE INTO kv (id, blob) VALUES ('workspace', '{}')")
                conn.commit()
                torn = 0
                stopped = False

                def reader():
                    nonlocal torn
                    c = self._connect(db_path)
                    while not stopped:
                        try:
                            json.loads(c.execute(
                                "SELECT blob FROM kv WHERE id='workspace'").fetchone()[0])
                        except Exception:
                            torn += 1
                    c.close()
                thread = threading.Thread(target=reader)
                thread.start()
                for i in range(writes):
                    conn.execute("REPLACE INTO kv (id, blob) VALUES ('workspace', ?)",
                                 (json.dumps({"i": i}),))
                    conn.commit()
                stopped = True
                thread.join()
                conn.close()
                return {"ok": True, "torn_reads": torn, "writes": writes}
            if action == "corrupt_read":
                db_path.write_bytes(b'{"version": 1, TRUNCATED GARBAGE')
                try:
                    conn = sqlite3.connect(db_path)
                    conn.execute("SELECT * FROM kv LIMIT 1").fetchall()
                    conn.close()
                    return {"ok": True, "behavior": "recovered-default"}
                except Exception as exc:
                    return {"ok": True, "behavior": f"threw:{type(exc).__name__}"}
            return {"ok": False, "error": f"unknown action {action}"}
        finally:
            import shutil
            shutil.rmtree(data_dir, ignore_errors=True)


class PouchDbStore(Candidate):
    name = "pouchdb-store"
    stages = {"persistence"}
    NODE_DIR = VENVS / "pouchdb-node"

    def available(self):
        marker = self.NODE_DIR / "node_modules" / "pouchdb"
        if marker.exists():
            return True, ""
        VENVS.mkdir(exist_ok=True)
        self.NODE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if not (self.NODE_DIR / "package.json").exists():
                init = subprocess.run(["npm", "init", "-y"], cwd=self.NODE_DIR,
                                      capture_output=True, timeout=120)
                if init.returncode != 0:
                    raise RuntimeError(init.stderr.decode()[-300:])
            install = subprocess.run(["npm", "install", "pouchdb", "--no-audit",
                                      "--no-fund"], cwd=self.NODE_DIR,
                                     capture_output=True, timeout=900)
            if install.returncode != 0 or not marker.exists():
                raise RuntimeError(install.stderr.decode()[-300:])
            return True, ""
        except Exception as exc:
            import shutil
            shutil.rmtree(self.NODE_DIR, ignore_errors=True)  # purge failed download
            return False, f"install failed (purged): {exc}"

    def store_probe(self, action: str, payload: dict) -> dict:
        script = r"""
const [action, payloadJson] = [process.argv[2], process.argv[3]];
const payload = JSON.parse(payloadJson);
const fs = require('fs');
const path = require('path');
const os = require('os');
const PouchDB = require('pouchdb');

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pouch-'));
  try {
    const db = new PouchDB(path.join(dir, 'db'));
    if (action === 'write_read') {
      const n = payload.n ?? 50, docs = payload.docsPerWrite ?? 40;
      const timings = [];
      let rev;
      for (let i = 0; i < n; i++) {
        const doc = { _id: 'workspace', documents: Array.from({length: docs}, (_, j) => ({id: `doc-${i}-${j}`})) };
        if (rev) doc._rev = rev;
        const t0 = performance.now();
        rev = (await db.put(doc)).rev;
        timings.push(performance.now() - t0);
      }
      timings.sort((a, b) => a - b);
      console.log(JSON.stringify({ok: true, p50_ms: timings[Math.floor(n/2)],
        p95_ms: timings[Math.floor(n*0.95)], documents: docs}));
    } else if (action === 'concurrent') {
      const writers = payload.writers ?? ['A', 'B'], ops = payload.ops ?? 20;
      await Promise.all(writers.map(async (tag) => {
        for (let i = 0; i < ops; i++) await db.put({_id: `doc-${tag}-${i}`});
      }));
      const all = await db.allDocs();
      const expected = writers.length * ops;
      console.log(JSON.stringify({ok: true, expected, surviving: all.total_rows,
        lost: expected - all.total_rows}));
    } else if (action === 'atomicity') {
      const writes = payload.writes ?? 150;
      let torn = 0;
      for (let i = 0; i < writes; i++) {
        try {
          const d = await db.get('workspace').catch(() => null);
          await db.put({_id: 'workspace', i, ...(d ? {_rev: d._rev} : {})});
          const check = await db.get('workspace');
          if (typeof check.i !== 'number' && i > 0) torn += 1;
        } catch (e) { torn += 1; }
      }
      console.log(JSON.stringify({ok: true, torn_reads: torn, writes}));
    } else if (action === 'corrupt_read') {
      await db.put({_id: 'workspace', documents: [{id: 'd1'}]});
      await db.close();
      const log = fs.readdirSync(dir, {recursive: true}).map(String)
        .find((f) => f.endsWith('.log'));
      if (log) fs.writeFileSync(path.join(dir, log), Buffer.alloc(4096, 255));
      try {
        const db2 = new PouchDB(path.join(dir, 'db'));
        const doc = await db2.get('workspace').catch(() => null);
        const intact = doc && Array.isArray(doc.documents) && doc.documents.length === 1;
        console.log(JSON.stringify({ok: true,
          behavior: intact ? 'recovered-default' : 'recovered-but-lost-data'}));
      } catch (e) {
        console.log(JSON.stringify({ok: true, behavior: `threw:${e.name}`}));
      }
    } else {
      console.log(JSON.stringify({ok: false, error: 'unknown action'}));
    }
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
})().catch((e) => { console.log(JSON.stringify({ok: false, error: String(e)})); process.exit(3); });
"""
        script_path = self.NODE_DIR / "probe.cjs"
        script_path.write_text(script)
        proc = subprocess.run(["node", str(script_path), action, json.dumps(payload)],
                              cwd=self.NODE_DIR, capture_output=True, timeout=300)
        try:
            last = [l for l in proc.stdout.decode().splitlines() if l.strip()][-1]
            return json.loads(last)
        except Exception:
            return {"ok": False,
                    "error": f"pouch probe: {proc.stderr.decode()[-200:]}"}


CANDIDATES = [SqliteStore, PouchDbStore]
