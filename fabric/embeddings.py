"""Optional on-device embeddings. No source text leaves the machine.

The model identifier includes the actual weight/tokenizer file hashes, preventing
vectors from a different model artifact being silently mixed into retrieval.
"""

import hashlib
import math
import struct
import threading
from pathlib import Path

from .core import FabricError, now

MODEL = "BAAI/bge-small-en-v1.5"


class LocalEmbedder:
    def __init__(self, cache, allow_download=False):
        try:
            import onnxruntime as ort
            ort.disable_telemetry_events()
            from fastembed import TextEmbedding
        except ImportError as e:
            raise FabricError("Install the optional semantic extra first.", "not_enabled", 409) from e
        self.lock = threading.Lock()
        try:
            self.engine = TextEmbedding(model_name=MODEL, cache_dir=str(Path(cache).resolve()), threads=1,
                                        providers=["CPUExecutionProvider"], local_files_only=not allow_download)
        except Exception as e:
            raise FabricError("Embedding weights are unavailable. Run embed --download-model explicitly first.", "not_enabled", 409) from e
        # These attributes belong to the pinned FastEmbed release. Changing it
        # requires a contract check, not an unbounded provider config passthrough.
        root = Path(self.engine.model._model_dir)
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in {".onnx", ".json", ".txt"})
        fingerprint = hashlib.sha256()
        for path in files:
            fingerprint.update(path.relative_to(root).as_posix().encode())
            with path.open("rb") as stream:
                while block := stream.read(1024*1024):
                    fingerprint.update(block)
        self.model = MODEL + ":" + fingerprint.hexdigest()

    @staticmethod
    def normalize(vector):
        values = [float(v) for v in vector]
        norm = math.sqrt(sum(v*v for v in values))
        if len(values) != 384 or not math.isfinite(norm) or norm == 0:
            raise FabricError("Invalid local embedding result.", "model_invalid", 502)
        return [v/norm for v in values]

    def documents(self, texts):
        with self.lock:
            return [self.normalize(v) for v in self.engine.passage_embed(texts, batch_size=16)]

    def query(self, text):
        with self.lock:
            return self.normalize(next(self.engine.query_embed(text)))


def index_documents(store, embedder):
    """Local operator only; generate only missing current-passage/model vectors."""
    store.init()
    with store.connect() as db:
        rows = db.execute("""SELECT p.id,p.text FROM passages p JOIN documents d ON d.id=p.document_id
            JOIN connections c ON c.id=d.connection_id LEFT JOIN vectors v ON v.passage_id=p.id AND v.model=?
            WHERE d.active=1 AND c.active=1 AND v.passage_id IS NULL ORDER BY p.id LIMIT 501""", (embedder.model,)).fetchall()
    if len(rows) > 500:
        raise FabricError("Embedding pass capped at 500 changed passages. Use a smaller selected corpus.", "budget_exceeded", 413)
    # Do not hold a write lock while running inference. Revalidate source liveness at commit.
    vectors = embedder.documents([r["text"] for r in rows]) if rows else []
    if len(vectors) != len(rows):
        raise FabricError("Embedding model returned the wrong batch size.")
    with store.connect() as db:
        written = 0
        for row, vector in zip(rows, vectors):
            current = db.execute("""SELECT 1 FROM passages p JOIN documents d ON d.id=p.document_id
                JOIN connections c ON c.id=d.connection_id WHERE p.id=? AND p.text=? AND d.active=1 AND c.active=1""",
                (row["id"], row["text"])).fetchone()
            if current:
                written += db.execute("INSERT OR IGNORE INTO vectors VALUES (?,?,?)",
                                      (row["id"], embedder.model, struct.pack("<384f", *vector))).rowcount
    return {"embedded_passages": written, "model": embedder.model, "dimensions":384,
            "external_model_calls":0, "external_model_cost_usd":0, "completed_at":now()}


def retrieve(store, db, ident, allowed, query, limit, strategy, lexical):
    # Authorization runs in SQL before vectors are loaded or ranked. No global
    # ANN search followed by a tenant post-filter, even for this tiny POC.
    rows = db.execute(f"""SELECT p.id,v.embedding FROM passages p JOIN documents d ON d.id=p.document_id
        JOIN connections c ON c.id=d.connection_id JOIN vectors v ON v.passage_id=p.id AND v.model=?
        WHERE d.active=1 AND c.active=1 AND c.collection_id IN ({store._in(allowed)})
        AND (d.principal='' OR d.principal=?)
        AND (coalesce(json_extract(c.config,'$.principal'),'')='' OR json_extract(c.config,'$.principal')=?)
        ORDER BY p.id LIMIT 5001""", (store.embedder.model,*allowed,ident["id"],ident["id"])).fetchall()
    if len(rows) > 5000:
        raise FabricError("Semantic POC capped at 5,000 permitted vectors. Narrow the selected corpus.", "budget_exceeded", 413)
    if not rows:
        # Do not encode queries if the identity has no eligible vectors.
        return {"items":lexical["items"][:limit] if strategy=="hybrid" else [], "retrieval":strategy,
                "semantic_coverage":"No eligible indexed vectors. Run the operator embed command after sync.",
                "local_embedding_calls":0,
                "has_more":(lexical["has_more"] or len(lexical["items"])>limit) if strategy=="hybrid" else False}
    vector = store.embedder.query(query)
    scored=[]
    for row in rows:
        try:
            candidate=struct.unpack("<384f",row["embedding"])
        except struct.error as e:
            raise FabricError("Invalid vector index. Rebuild it.") from e
        score=sum(a*b for a,b in zip(vector,candidate))
        if score >= .35:
            scored.append((row["id"],score))
    scored.sort(key=lambda value:(-value[1],value[0]))
    semantic=[pid for pid,_ in scored[:24]]
    ranks={}
    lists=[semantic] if strategy=="semantic" else [[i["ref"] for i in lexical["items"]],semantic]
    for ordered in lists:
        for i, pid in enumerate(ordered):
            ranks[pid]=ranks.get(pid,0)+1/(60+i+1)
    ids=sorted(ranks,key=lambda pid:(-ranks[pid],pid))
    return {"items":[store._document_item(store._passage(db,ident,allowed,pid)) for pid in ids[:limit]],
            "has_more":len(ids)>limit, "retrieval":strategy+"_rrf" if strategy=="hybrid" else "local_cosine",
            "model":store.embedder.model, "local_embedding_calls":1,
            "semantic_coverage":"Selected current passages with matching model hashes only. New syncs need an explicit embed pass.",
            "coverage":"Selected documents only; semantic similarity does not establish factual support or absence."}
