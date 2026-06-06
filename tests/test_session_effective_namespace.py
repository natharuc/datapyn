"""Tests for Session.effective_namespace (panel + autocomplete parity)."""

from types import SimpleNamespace

from src.core.session import Session


class _FakeConnector:
    db_type = "mysql"
    engine = SimpleNamespace(url="mysql+pymysql://root:***@localhost:3306/seducao")
    connection_params = {
        "host": "localhost",
        "port": 3306,
        "database": "seducao",
        "username": "root",
    }
    is_connected = True


def test_effective_namespace_includes_connection_metadata():
    session = Session("s1")
    session.set_connection("SEDUCAO", _FakeConnector())
    session.update_namespace({"block1": [1, 2]})

    ns = session.effective_namespace()

    assert ns["block1"] == [1, 2]
    assert ns["db_connection_name"] == "SEDUCAO"
    assert ns["db_username"] == "root"
    assert ns["db_host"] == "localhost"
    assert ns["db_type"] == "mysql"
