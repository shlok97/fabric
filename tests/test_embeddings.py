import os

import pytest

from fabric.core import FabricError, canonical
from fabric.embeddings import LocalEmbedder, index_documents
from fabric.sources import sync_folder


@pytest.fixture(scope="session")
def embedder():
    cache = os.getenv("FABRIC_TEST_MODEL_CACHE")
    if not cache:
        pytest.skip("Set FABRIC_TEST_MODEL_CACHE for the real, offline model tests.")
    pytest.importorskip("fastembed")
    return LocalEmbedder(cache)


def test_semantic_mode_fails_explicitly_if_disabled(demo):
    store, keys, _ = demo
    with pytest.raises(FabricError) as e:
        store.execute(keys["alice"],"search",{"query":"company sales","strategy":"semantic"})
    assert e.value.code == "not_enabled"


def test_real_model_dimension_and_hash(embedder):
    vector = embedder.query("A fictional company report")
    assert len(vector) == 384
    assert abs(sum(v*v for v in vector) - 1) < .00001
    assert len(embedder.model.split(":")[1]) == 64


def test_real_semantic_search_and_idempotent_index(demo, embedder):
    store,keys,_ = demo
    store.embedder = embedder
    assert index_documents(store,embedder)["embedded_passages"] == 8
    assert index_documents(store,embedder)["embedded_passages"] == 0
    lexical=store.execute(keys["alice"],"search",{"query":"manufacturing facilities increased turnover"})
    semantic=store.execute(keys["alice"],"search",{"query":"manufacturing facilities increased turnover","strategy":"semantic","limit":3})
    assert lexical["items"] == []
    assert any(i["locator"]["document"] == "results.md" for i in semantic["items"])
    assert semantic["receipt"]["local_embedding_calls"] == 1
    assert semantic["receipt"]["external_model_calls"] == 0


@pytest.mark.parametrize("strategy",["semantic","hybrid"])
def test_real_vector_retrieval_respects_scope_and_revocation(demo, embedder, strategy):
    store,keys,_ = demo
    store.embedder = embedder
    index_documents(store,embedder)
    for identity,forbidden in [("alice",["CEDAR-SAFFRON-963","LICENCE-ONLY-159"]),
                                ("bob",["ALICE-INDIGO-852","CEDAR-SAFFRON-963","LICENCE-ONLY-159"]),
                                ("chandra",["KITE-MARIGOLD-741","ALICE-INDIGO-852","LICENCE-ONLY-159"])]:
        result=canonical(store.execute(keys[identity],"search",{"query":"Northstar research estimate diligence","strategy":strategy,"limit":12}))
        assert all(secret not in result for secret in forbidden)
    with store.connect() as db:
        db.execute("DELETE FROM grants WHERE collection_id='kite-private'")
    result=canonical(store.execute(keys["alice"],"search",{"query":"Paper Kite research estimate","strategy":strategy,"limit":12}))
    assert "KITE-MARIGOLD-741" not in result


def test_vector_update_delete_lifecycle(demo,embedder):
    store,keys,path=demo
    store.embedder=embedder
    index_documents(store,embedder)
    file=path/"sources/kite/estimate.md"
    file.write_text("# Revised forecast\nPaper Kite expects much slower Northstar expansion. New marker KITE-LOTUS-246.")
    sync_folder(store,"kite-docs")
    assert index_documents(store,embedder)["embedded_passages"] == 1
    result=canonical(store.execute(keys["alice"],"search",{"query":"Paper Kite forecast expansion","strategy":"hybrid"}))
    assert "KITE-LOTUS-246" in result and "KITE-MARIGOLD-741" not in result
    file.unlink()
    sync_folder(store,"kite-docs")
    result=canonical(store.execute(keys["alice"],"search",{"query":"Paper Kite forecast expansion","strategy":"hybrid"}))
    assert "KITE-LOTUS-246" not in result


def test_zero_eligible_vectors_do_not_embed_query(demo,embedder,monkeypatch):
    store,keys,_=demo
    store.embedder=embedder
    index_documents(store,embedder)
    with store.connect() as db:
        db.execute("DELETE FROM grants")
    def forbidden(_):
        raise AssertionError("Query embedded despite having no permitted vectors")
    monkeypatch.setattr(embedder,"query",forbidden)
    result=store.execute(keys["alice"],"search",{"query":"private forecast","strategy":"semantic"})
    assert result["items"] == [] and result["receipt"]["local_embedding_calls"] == 0
