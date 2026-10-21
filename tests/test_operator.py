import json
from pathlib import Path

import pytest

from fabric.core import FabricError, Store, canonical
from fabric.demo import create_demo
from fabric.sources import provision


def test_demo_restart_preserves_source_edits_and_keys(demo):
    store,keys,path=demo
    file=path/"sources/kite/estimate.md"
    file.write_text("An operator's local edit")
    again,newkeys=create_demo(path)
    assert again.path==store.path and newkeys==keys
    assert file.read_text()=="An operator's local edit"


def test_bootstrap_refuses_cross_tenant_grant_atomically(tmp_path):
    store=Store(tmp_path/"fabric.db")
    config={"workspace":"x","principals":[{"id":"alice","tenant":"a","name":"Alice"}],
            "collections":[{"id":"private","tenant":"a","name":"Private","grants":[{"tenant":"b"}]}],"connections":[]}
    with pytest.raises(FabricError):
        provision(store,config)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM principals").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM collections").fetchone()[0]==0


def test_example_bootstraps_but_not_twice(tmp_path):
    config=json.loads((Path(__file__).resolve().parents[1]/"examples/config.json").read_text())
    store=Store(tmp_path/"fabric.db")
    keys=provision(store,config)
    assert set(keys)=={"analyst-a","analyst-b"}
    with store.connect() as db:
        assert all(value not in canonical([dict(r) for r in db.execute("SELECT * FROM principals")]) for value in keys.values())
    with pytest.raises(FabricError):
        provision(store,config)
