#!/usr/bin/env python3
"""Reproducible deterministic retrieval checks and local scale diagnostic.

This does NOT benchmark an LLM or compare against Claude Code/Mem0. The full
authorized-document byte baseline is a storage diagnostic, not a strong agent.
"""

import argparse
import json
import math
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fabric.core import FabricError, canonical, now
from fabric.demo import create_demo


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)]


def run(scale_rows=100_000, repetitions=100, model_cache=None):
    with tempfile.TemporaryDirectory(prefix="fabric-eval-") as temp:
        store, keys = create_demo(Path(temp)/"demo")
        embedding_index=None
        if model_cache:
            from fabric.embeddings import LocalEmbedder, index_documents
            store.embedder=LocalEmbedder(model_cache)
            embedding_index=index_documents(store,store.embedder)
        cases = []
        for principal in ("alice", "bob", "chandra"):
            key = keys[principal]
            corpus = canonical(store.execute(key, "search", {"query": "Northstar KITE CEDAR ALICE LICENCE"}))
            hidden = ["LICENCE-ONLY-159"] + (["CEDAR-SAFFRON-963"] if principal != "chandra" else ["KITE-MARIGOLD-741"])
            if principal != "alice":
                hidden += ["ALICE-INDIGO-852"]
            cases.append({"id": principal+"-isolation", "pass": all(marker not in corpus for marker in hidden)})
            for query, marker in [("capacity expansion", "Capacity expansion"), ("input copper costs", "Copper input costs"),
                                  ("exact period basis", "Use the exact period"), ("content hashes", "content hashes")]:
                items = store.execute(key, "search", {"query": query, "limit": 3})["items"]
                cases.append({"id": principal+"-"+query, "pass": any(marker in i["text"] for i in items)})
            for descriptor, expected in [("market.revenue", 120), ("market.roe", .18), ("market.dividend", None),
                                          (("kite.estimate" if principal != "chandra" else "cedar.estimate"), 110 if principal != "chandra" else 135)]:
                items = store.execute(key,"read",{"descriptor_id":descriptor,"subjects":["NORTHSTAR"],"period":"FY2026","basis":"consolidated"})["items"]
                cases.append({"id":principal+"-"+descriptor,"pass": len(items)==1 and items[0]["row"]["value"]==expected})
            forbidden = "cedar.estimate" if principal != "chandra" else "kite.estimate"
            try:
                store.execute(key,"read",{"descriptor_id":forbidden,"subjects":["NORTHSTAR"],"period":"FY2026","basis":"consolidated"})
                denied = False
            except FabricError as e:
                denied = e.status == 404
            cases.append({"id":principal+"-private-descriptor-denied","pass":denied})

        source = Path(temp)/"demo/market.db"
        if model_cache:
            lexical=store.execute(keys["alice"],"search",{"query":"manufacturing facilities increased turnover"})
            semantic=store.execute(keys["alice"],"search",{"query":"manufacturing facilities increased turnover","strategy":"semantic","limit":3})
            cases.append({"id":"semantic-paraphrase-fixture","pass":not lexical["items"] and any(i["locator"]["document"]=="results.md" for i in semantic["items"])})
        with sqlite3.connect(source) as db:
            db.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
                ((f"OTHER-{i}", "revenue", "FY2026", "consolidated", float(i), "inr_cr", "2026-05-15T00:00:00.000Z") for i in range(scale_rows)))
        durations, bytes_returned = {"search":[], "read":[]}, []
        if model_cache:
            durations["hybrid"]=[]
        for _ in range(repetitions):
            if model_cache:
                start=time.perf_counter()
                store.execute(keys["alice"],"search",{"query":"manufacturing facilities increased turnover","strategy":"hybrid","limit":3})
                durations["hybrid"].append((time.perf_counter()-start)*1000)
            for operation, args in [("search", {"query":"capacity expansion", "limit":3}),
                                     ("read", {"descriptor_id":"market.revenue","subjects":["NORTHSTAR"],"period":"FY2026","basis":"consolidated"})]:
                start = time.perf_counter()
                result = store.execute(keys["alice"], operation, args)
                durations[operation].append((time.perf_counter()-start)*1000)
                if operation == "search":
                    bytes_returned.append(result["receipt"]["evidence_bytes"])
        with store.connect() as db:
            identity = store.authenticate(db, keys["alice"])
            allowed = store.allowed(db, identity)
            full = [dict(r) for r in db.execute(
                f"SELECT p.text FROM passages p JOIN documents d ON d.id=p.document_id JOIN connections c ON c.id=d.connection_id "
                f"WHERE d.active=1 AND c.active=1 AND c.collection_id IN ({store._in(allowed)}) AND (d.principal='' OR d.principal=?)",
                (*allowed,identity["id"]))]
            passages = db.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        return {"created_at":now(), "kind":"deterministic_local_diagnostic", "cases":cases,
                "passed":sum(c["pass"] for c in cases), "total":len(cases), "scale_rows_added":scale_rows,
                "source_database_bytes":source.stat().st_size, "indexed_passages":passages,
                "embedded_numeric_rows":0, "external_model_calls":0, "external_model_cost_usd":0,
                "embedding_index":embedding_index,
                "repetitions":repetitions,
                "latency_ms":{op:{"p50":round(statistics.median(v),3),"p95":round(percentile(v,.95),3)} for op,v in durations.items()},
                "document_context_diagnostic":{"all_authorized_passage_text_bytes":len(canonical(full).encode()),
                     "retrieved_bundle_bytes_median":statistics.median(bytes_returned)},
                "limitations":["Synthetic corpus and indexed local SQLite source; timings are not production SLAs.",
                                "No LLM answer quality, actual tokenizer counts, Mem0, Jev or Claude comparison measured.",
                                "Full-context byte comparison is not an agent baseline or product hypothesis validation."]}


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output", default="reports/local/evaluation.json")
    p.add_argument("--rows",type=int,default=100_000)
    p.add_argument("--repetitions",type=int,default=100)
    p.add_argument("--model-cache",help="Optional already downloaded local model; includes semantic checks and warm hybrid timings")
    a=p.parse_args()
    if not 0 <= a.rows <= 1_000_000 or not 1 <= a.repetitions <= 1000:
        p.error("rows must be 0–1,000,000; repetitions 1–1,000")
    result=run(a.rows,a.repetitions,a.model_cache)
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+"\n")
    print(canonical({k:result[k] for k in ("passed","total","latency_ms","scale_rows_added","source_database_bytes","external_model_cost_usd")}))
    raise SystemExit(0 if result["passed"]==result["total"] else 1)
