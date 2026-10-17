from recallmesh.agents import AgentContext, CoordinatorAgent


class FakeStore:
    def __init__(self): self.calls = []
    def search_memories(self, *args): self.calls.append(("search", args)); return []
    def create_task(self, *args): self.calls.append(("task", args))
    def handoff(self, *args): self.calls.append(("handoff", args))
    def save_memory(self, *args): self.calls.append(("memory", args))


def test_coordinator_handoff_pipeline():
    store = FakeStore()
    result = CoordinatorAgent(store).handle(AgentContext("demo", "alice"), "prepare briefing")
    assert result["result"].startswith("Rule-based")
    assert [call[0] for call in store.calls] == ["search", "task", "handoff", "memory"]

