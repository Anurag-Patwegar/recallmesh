import os
import uuid

import pytest

from memory.graph_store import GraphStore


@pytest.fixture(scope="module")
def store():
    repository = GraphStore()
    ok, message = repository.connection_test()
    if not ok:
        pytest.skip(f"real FalkorDB required: {message}")
    return repository


def test_create_retrieve_update_and_user_isolation(store):
    tenant = f"test_{uuid.uuid4().hex[:10]}"
    first = store.create_memory(tenant, "m1", "alice", "personal", "semantic", "Alice prefers tea")
    assert first
    assert len(store.retrieve_relevant_memory(tenant, "alice", "tea")) == 1
    assert store.retrieve_relevant_memory(tenant, "bob", "tea") == []

    store.supersede_memory(tenant, "m1", "m2", "alice", "personal", "semantic", "Alice prefers coffee")
    assert store.retrieve_relevant_memory(tenant, "alice", "tea") == []
    assert len(store.retrieve_relevant_memory(tenant, "alice", "coffee")) == 1


def test_shared_memory_is_available_within_tenant(store):
    tenant = f"shared_{uuid.uuid4().hex[:10]}"
    store.create_memory(tenant, "shared1", "alice", "shared", "procedural", "Deploy with docker compose")
    assert len(store.retrieve_relevant_memory(tenant, "bob", "docker")) == 1

