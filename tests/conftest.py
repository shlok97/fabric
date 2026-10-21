import pytest

from fabric.demo import create_demo


@pytest.fixture
def demo(tmp_path):
    store, keys = create_demo(tmp_path / "demo")
    return store, keys, tmp_path / "demo"
