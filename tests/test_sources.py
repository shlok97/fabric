import hashlib
import sqlite3

import pytest

from fabric.core import FabricError, canonical
from fabric.sources import chunks, sync_folder
from test_isolation import read, search


def test_read_is_live_bounded_and_never_mutates_source(demo):
    s, k, path = demo
    source = path / "market.db"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = read(s, k["alice"])
    assert result["items"][0]["row"]["value"] == 120
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(source) as db:
        db.execute("UPDATE facts SET value=121 WHERE metric='revenue' AND value=120")
    assert read(s, k["alice"])["items"][0]["row"]["value"] == 121
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": result["items"][0]["ref"]})


def test_numeric_citation_revalidates_source_and_scope(demo):
    s, k, _ = demo
    item = read(s, k["alice"])["items"][0]
    assert s.execute(k["alice"], "get_evidence", {"ref": item["ref"]})["items"][0]["row"] == item["row"]
    with s.connect() as db:
        db.execute("DELETE FROM grants WHERE collection_id='shared' AND tenant='paper-kite'")
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": item["ref"]})


def test_descriptor_revision_invalidates_numeric_citation(demo):
    s, k, _ = demo
    ref = read(s, k["alice"])["items"][0]["ref"]
    with s.connect() as db:
        db.execute("UPDATE descriptors SET version=version+1 WHERE id='market.revenue'")
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": ref})


def test_vintage_cutoff_basis_null_and_units(demo):
    s, k, _ = demo
    assert read(s, k["alice"], as_of="2026-05-10T00:00:00Z")["items"][0]["row"]["value"] == 115
    assert not read(s, k["alice"], as_of="2026-04-01T00:00:00Z")["items"]
    assert not read(s, k["alice"], basis="standalone")["items"]
    roe = read(s, k["alice"], "market.roe")["items"][0]["row"]
    assert roe["value"] == .18 and roe["unit"] == "fraction"
    dividend = read(s, k["alice"], "market.dividend")["items"][0]["row"]
    assert dividend["value"] is None and dividend["status"] == "unavailable"


@pytest.mark.parametrize("args", [{"subjects": []}, {"subjects": ["UNKNOWN"]}, {"subjects": ["NORTHSTAR"]*21},
                                   {"limit": 101}, {"limit": True}, {"basis": "any"}, {"as_of": "2026-05-10"},
                                   {"subjects": "NORTHSTAR"}, {"period": None}])
def test_invalid_read_plan_rejected(demo, args):
    s, k, _ = demo
    with pytest.raises(FabricError):
        read(s, k["alice"], **args)


def test_wrong_source_unit_refuses_read(demo):
    s, k, path = demo
    with sqlite3.connect(path/"market.db") as db:
        db.execute("UPDATE facts SET unit='percent' WHERE metric='roe'")
    with pytest.raises(FabricError) as e:
        read(s, k["alice"], "market.roe")
    assert e.value.code == "source_invalid"


def test_missing_source_visible_failure(demo):
    s, k, path = demo
    (path/"market.db").unlink()
    with pytest.raises(FabricError) as e:
        read(s, k["alice"])
    assert e.value.code == "source_unavailable"


def test_snapshot_is_not_mislabelled_live_or_historical(demo):
    import json
    s,k,_=demo
    with s.connect() as db:
        config=json.loads(db.execute("SELECT config FROM connections WHERE id='market-db'").fetchone()[0])
        config["snapshot"]={"captured_at":"2026-05-16T00:00:00Z","vintage_history_included":False}
        db.execute("UPDATE connections SET config=? WHERE id='market-db'",(canonical(config),))
    item=read(s,k["alice"])["items"][0]
    assert item["freshness"]=="captured_snapshot"
    assert s.execute(k["alice"],"get_evidence",{"ref":item["ref"]})["items"][0]["freshness"]=="captured_snapshot"
    with pytest.raises(FabricError):
        read(s,k["alice"],as_of="2026-05-10T00:00:00Z")


def test_oversized_evidence_fails_visibly_and_records_no_source_text(demo):
    s,k,path=demo
    file=path/"sources/kite/unicode.md"
    file.write_text(("नॉर्थस्टार "*120+"\n")*24)
    sync_folder(s,"kite-docs")
    with pytest.raises(FabricError) as error:
        search(s,k["alice"],"नॉर्थस्टार",limit=12)
    assert error.value.code=="budget_exceeded"
    with s.connect() as db:
        failure=db.execute("SELECT * FROM receipts WHERE status='budget_exceeded'").fetchone()
        assert failure is not None and "नॉर्थस्टार" not in canonical(dict(failure))


def test_idempotent_update_delete_and_stale_citations(demo):
    s, k, path = demo
    first = search(s, k["alice"], "KITE MARIGOLD")["items"][0]
    assert sync_folder(s, "kite-docs")["changed"] == 0
    assert search(s, k["alice"], "KITE MARIGOLD")["items"][0]["ref"] == first["ref"]
    file = path/"sources/kite/estimate.md"
    file.write_text("# New estimate\nKITE-LOTUS-246 replaces the previous Northstar estimate.\n")
    report = sync_folder(s, "kite-docs")
    assert report["changed"] == 1 and report["unchanged"] == 1
    assert not search(s, k["alice"], "MARIGOLD")["items"]
    assert "KITE-LOTUS-246" in canonical(search(s, k["alice"], "LOTUS"))
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": first["ref"]})
    new = search(s, k["alice"], "LOTUS")["items"][0]
    file.unlink()
    assert sync_folder(s, "kite-docs")["removed"] == 1
    assert not search(s, k["alice"], "LOTUS")["items"]
    with pytest.raises(FabricError):
        s.execute(k["alice"], "get_evidence", {"ref": new["ref"]})


def test_failed_sync_retains_previous_snapshot_and_reports_error(demo):
    s, k, path = demo
    (path/"sources/kite/estimate.md").unlink()
    bad = path/"sources/kite/too-large.md"
    bad.write_text("x"*262145)
    with pytest.raises(FabricError):
        sync_folder(s, "kite-docs")
    assert "KITE-MARIGOLD-741" in canonical(search(s, k["alice"], "MARIGOLD"))
    status = s.execute(k["alice"], "status")
    assert next(c for c in status["sources"] if c["id"] == "kite-docs")["last_error"]


def test_symlink_sources_are_not_followed(demo, tmp_path):
    s, k, path = demo
    outside = tmp_path/"private.txt"
    outside.write_text("OUTSIDE-SECRET")
    (path/"sources/shared/link.md").symlink_to(outside)
    (path/"sources/shared/directory").symlink_to(tmp_path, target_is_directory=True)
    sync_folder(s, "shared-docs")
    assert not search(s, k["alice"], "OUTSIDE SECRET")["items"]


def test_chunks_are_bounded_and_line_addressable():
    body = "first\n" + "x"*5000 + "\nlast"
    pieces = chunks(body)
    assert all(len(p[2]) <= 1800 for p in pieces)
    assert pieces[0] == (1,1,"first")
    assert all(start == end == 2 for start,end,_ in pieces[1:-1])
    assert pieces[-1] == (3,3,"last")


@pytest.mark.parametrize("query", ["\" OR *", "{}[] !", "a"*501, "", None])
def test_invalid_fts_input_is_not_sql(demo, query):
    s, k, _ = demo
    if query == '" OR *':
        assert isinstance(search(s, k["alice"], query)["items"], list)
    else:
        with pytest.raises(FabricError):
            search(s, k["alice"], query)
