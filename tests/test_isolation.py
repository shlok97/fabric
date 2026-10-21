import json
import pytest

from fabric.core import FabricError, canonical, digest


def search(store, key, q="Northstar estimate", **kw):
    return store.execute(key, "search", {"query": q, **kw})


def read(store, key, descriptor="market.revenue", **kw):
    return store.execute(key, "read", {"descriptor_id": descriptor, "subjects": ["NORTHSTAR"],
                                     "period": "FY2026", "basis": "consolidated", **kw})


@pytest.mark.parametrize("principal,visible,hidden", [
    ("alice", "KITE-MARIGOLD-741", ["CEDAR-SAFFRON-963", "LICENCE-ONLY-159"]),
    ("bob", "KITE-MARIGOLD-741", ["CEDAR-SAFFRON-963", "ALICE-INDIGO-852", "LICENCE-ONLY-159"]),
    ("chandra", "CEDAR-SAFFRON-963", ["KITE-MARIGOLD-741", "ALICE-INDIGO-852", "LICENCE-ONLY-159"]),
])
def test_tenant_corpus(demo, principal, visible, hidden):
    s, keys, _ = demo
    result = canonical(search(s, keys[principal], "Northstar KITE CEDAR ALICE LICENCE"))
    assert visible in result
    for secret in hidden:
        assert secret not in result


@pytest.mark.parametrize("operation,args", [
    ("status", {}), ("discover", {"query": "estimate"}),
    ("search", {"query": "secret"}), ("get_evidence", {"ref": "p_fake"}),
    ("read", {"descriptor_id": "kite.estimate", "subjects": ["NORTHSTAR"], "period": "FY2026", "basis": "consolidated"}),
])
def test_missing_and_unknown_credentials(demo, operation, args):
    s, _, _ = demo
    for key in (None, "", "invalid", "fabric_guess"):
        with pytest.raises(FabricError) as e:
            s.execute(key, operation, args)
        assert e.value.status == 401


@pytest.mark.parametrize("field,value", [("tenant", "cedar-house"), ("workspace", "other"),
                                         ("principal", "chandra"), ("owner", "other"),
                                         ("sql", "SELECT * FROM principals"), ("url", "https://evil.example")])
def test_model_cannot_override_scope(demo, field, value):
    s, keys, _ = demo
    with pytest.raises(FabricError):
        s.execute(keys["alice"], "search", {"query": "estimate", field: value})


def test_guessed_and_known_cross_tenant_references(demo):
    s, k, _ = demo
    passage = next(i for i in search(s, k["alice"])["items"] if i["collection"] == "kite-private")
    number = read(s, k["alice"], "kite.estimate")["items"][0]
    errors = []
    for ref in (passage["ref"], number["ref"], "p_guessed", "n_guessed"):
        with pytest.raises(FabricError) as e:
            s.execute(k["chandra"], "get_evidence", {"ref": ref})
        errors.append((e.value.status, str(e.value)))
    assert len(set(errors)) == 1


def test_principal_restriction_even_with_collection_grant(demo):
    s, k, _ = demo
    with s.connect() as db:
        db.execute("INSERT INTO grants VALUES ('alice-only','paper-kite','')")
    assert "ALICE-INDIGO-852" in canonical(search(s, k["alice"], "ALICE INDIGO"))
    assert not search(s, k["bob"], "ALICE INDIGO")["items"]
    assert "alice-docs" not in canonical(s.execute(k["bob"], "discover", {"query": "notes"}))


def test_revoked_grant_invalidates_existing_refs(demo):
    s, k, _ = demo
    ref = next(i["ref"] for i in search(s, k["alice"])["items"] if i["collection"] == "kite-private")
    with s.connect() as db:
        db.execute("DELETE FROM grants WHERE collection_id='kite-private'")
    assert "KITE-MARIGOLD" not in canonical(search(s, k["alice"]))
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": ref})
    with pytest.raises(FabricError):
        read(s, k["alice"], "kite.estimate")


def test_shared_is_not_public_and_revocation_is_per_tenant(demo):
    s, k, _ = demo
    assert read(s, k["alice"])["items"][0]["row"]["value"] == 120
    assert read(s, k["chandra"])["items"][0]["row"]["value"] == 120
    with s.connect() as db:
        db.execute("DELETE FROM grants WHERE collection_id='shared' AND tenant='paper-kite'")
    with pytest.raises(FabricError):
        read(s, k["alice"])
    assert read(s, k["chandra"])["items"]
    assert "LICENCE-ONLY-159" not in canonical(search(s, k["chandra"], "LICENCE"))


def test_disabled_identity_and_connection_take_effect_immediately(demo):
    s, k, _ = demo
    ref = next(i["ref"] for i in search(s, k["alice"])["items"] if i["collection"] == "kite-private")
    with s.connect() as db:
        db.execute("UPDATE connections SET active=0 WHERE id='kite-docs'")
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": ref})
    with s.connect() as db:
        db.execute("UPDATE principals SET active=0 WHERE id='alice'")
    with pytest.raises(FabricError) as e:
        s.execute(k["alice"], "status")
    assert e.value.status == 401


def test_workspace_boundary_even_with_mistaken_tenant_grant(demo):
    s, k, _ = demo
    with s.connect() as db:
        db.execute("INSERT INTO principals VALUES ('outsider','other-workspace','paper-kite','Outsider',?,1)", (digest("outside"),))
    result = s.execute("outside", "discover", {"query": "revenue"})
    assert result["items"] == []
    assert search(s, "outside")["items"] == []


def test_unauthorized_documents_cannot_displace_top_k(demo):
    s, k, _ = demo
    ref = next(i["ref"] for i in search(s, k["chandra"])["items"] if i["collection"] == "cedar-private")
    with s.connect() as db:
        doc = db.execute("SELECT document_id FROM passages WHERE id=?", (ref,)).fetchone()[0]
        for i in range(40):
            pid = f"p_cedar_{i}"
            db.execute("INSERT INTO passages VALUES (?,?,?,? ,1,1)", (pid, doc, i+10, "marigold "*20))
            db.execute("INSERT INTO passage_fts VALUES (?,?)", (pid, "marigold "*20))
    result = search(s, k["alice"], "marigold", limit=1)
    assert len(result["items"]) == 1
    assert result["items"][0]["collection"] == "kite-private"


def test_source_injection_is_inert_data(demo):
    s, k, _ = demo
    data = search(s, k["alice"], "IGNORE RULES")
    assert "IGNORE ALL RULES" in canonical(data)
    assert "CEDAR-SAFFRON-963" not in canonical(data)
    assert data["receipt"]["external_model_calls"] == 0
    assert data["receipt"]["source_calls"] == 0


def test_audit_contains_no_queries_or_private_text(demo):
    s, k, _ = demo
    search(s, k["alice"], "Northstar KITE-MARIGOLD-741")
    with s.connect() as db:
        audit = canonical([dict(r) for r in db.execute("SELECT * FROM receipts")])
    for value in ("Northstar", "KITE-MARIGOLD-741", k["alice"]):
        assert value not in audit


def test_source_audience_change_takes_effect_before_resync(demo):
    s, k, _ = demo
    passage = next(i["ref"] for i in search(s, k["bob"])["items"] if i["collection"] == "kite-private")
    numeric = read(s, k["bob"], "kite.estimate")["items"][0]["ref"]
    with s.connect() as db:
        for cid in ("kite-docs", "kite-db"):
            config = json.loads(db.execute("SELECT config FROM connections WHERE id=?", (cid,)).fetchone()[0])
            config["principal"] = "alice"
            db.execute("UPDATE connections SET config=? WHERE id=?", (canonical(config), cid))
    assert "KITE-MARIGOLD-741" not in canonical(search(s, k["bob"]))
    assert "kite-db" not in canonical(s.execute(k["bob"], "discover", {"query": "estimate"}))
    for ref in (passage, numeric):
        with pytest.raises(FabricError):
            s.execute(k["bob"], "get_evidence", {"ref": ref})
    with pytest.raises(FabricError):
        read(s, k["bob"], "kite.estimate")
    assert read(s, k["alice"], "kite.estimate")["items"]
