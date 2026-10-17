from recallmesh.store import validate_id


def test_valid_tenant_ids():
    assert validate_id("tenant_1") == "tenant_1"


def test_rejects_cypher_injection():
    import pytest
    with pytest.raises(ValueError):
        validate_id("tenant` MATCH (n)", "tenant")


def test_queries_are_parameterized():
    from pathlib import Path
    source = Path("recallmesh/store.py").read_text()
    assert "query(tenant, cypher, locals())" in source
    assert "f\"{self.prefix}_{tenant}\"" in source

