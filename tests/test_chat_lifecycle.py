import uuid

import pytest

from agents.chat_agent import DeterministicChatAgent
from memory.graph_store import GraphStore


@pytest.fixture(scope="module")
def store():
    repository = GraphStore()
    ok, message = repository.connection_test()
    if not ok:
        pytest.skip(f"real FalkorDB required: {message}")
    return repository


def test_chat_persists_across_sessions_and_uses_graph_memory(store):
    tenant = f"chat_{uuid.uuid4().hex[:10]}"
    user = "alice"
    first_session = f"session_{uuid.uuid4().hex[:10]}"
    second_session = f"session_{uuid.uuid4().hex[:10]}"
    agent = DeterministicChatAgent(store)

    saved = agent.handle(tenant, user, first_session, "My preferred stack is Python, FastAPI and FalkorDB.")
    assert saved.saved_memory[0]["memory_type"] == "semantic"

    asked = agent.handle(tenant, user, second_session, "What is my preferred stack?")
    assert asked.retrieved_memories
    assert "Python, FastAPI and FalkorDB" in asked.response
    assert store.get_turns(tenant, second_session)
    assert store.get_recent_turns(tenant, user)
    restarted_store = GraphStore()
    assert restarted_store.retrieve_relevant_memory(tenant, user, "preferred stack")


def test_procedural_memory_is_retrieved(store):
    tenant = f"proc_{uuid.uuid4().hex[:10]}"
    agent = DeterministicChatAgent(store)
    agent.handle(tenant, "alice", f"session_{uuid.uuid4().hex[:10]}", "Our release process is to run tests, build the image, obtain QA approval, deploy and verify health.")
    result = agent.handle(tenant, "alice", f"session_{uuid.uuid4().hex[:10]}", "What is our release process?")
    assert any(item["memory_type"] == "procedural" for item in result.retrieved_memories)


def test_chat_fact_change_supersedes_old_memory(store):
    tenant = f"change_{uuid.uuid4().hex[:10]}"
    agent = DeterministicChatAgent(store)
    agent.handle(tenant, "alice", f"session_{uuid.uuid4().hex[:10]}", "My preferred stack is Python and FastAPI.")
    result = agent.handle(tenant, "alice", f"session_{uuid.uuid4().hex[:10]}", "My preferred stack is Python, FastAPI and FalkorDB.")
    assert result.superseded_memory_id
    old = store.query(tenant, "MATCH (m:Memory {memory_id:$id}) RETURN m.active AS active", {"id": result.superseded_memory_id})
    assert old.result_set == [[False]]
