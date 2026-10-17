import uuid

from agents.chat_agent import DeterministicChatAgent
from memory.graph_store import GraphStore


def test_generic_fact_saved_in_later_session_retrieves_from_older_session():
    store = GraphStore()
    ok, message = store.connection_test()
    assert ok, message
    tenant = f"food_{uuid.uuid4().hex[:10]}"
    agent = DeterministicChatAgent(store)
    session_12 = f"session_12_{uuid.uuid4().hex[:8]}"
    session_5 = f"session_5_{uuid.uuid4().hex[:8]}"

    saved = agent.handle(tenant, "maya", session_12, "My favorite food is Dosa.")
    assert saved.saved_memory[0]["memory_type"] == "semantic"
    assert saved.saved_memory[0]["content"] == "My favorite food is Dosa."

    recalled = agent.handle(tenant, "maya", session_5, "What is my favorite food?")
    assert any(item["content"] == "My favorite food is Dosa." for item in recalled.retrieved_memories)
    assert "Dosa" in recalled.response
