"""Per-block database context must survive session save/restore."""

from source.src.core.session import Session
from source.src.editors.code_block import CodeBlock


class TestBlockDatabasePersistence:
    def test_to_dict_includes_explicit_database(self):
        block = CodeBlock()
        block.set_database_name("esim")
        data = block.to_dict()
        assert data["database_name"] == "esim"

    def test_from_dict_restores_explicit_database(self):
        block = CodeBlock.from_dict(
            {"language": "sql", "code": "SELECT 1", "database_name": "esim"}
        )
        assert block.get_database_name() == "esim"
        assert not block.uses_tab_default_database()

    def test_tab_default_database_not_serialized(self):
        block = CodeBlock()
        assert block.uses_tab_default_database()
        data = block.to_dict()
        assert "database_name" not in data

    def test_session_roundtrip_preserves_block_database(self):
        session = Session("s1", "Script")
        session._blocks = [
            {
                "language": "sql",
                "code": "SELECT 1",
                "block_name": "block1",
                "database_name": "esim",
            }
        ]
        session._database_context = "Gecon"

        restored = Session.deserialize(session.serialize())
        assert restored._database_context == "Gecon"
        assert restored._blocks[0]["database_name"] == "esim"
