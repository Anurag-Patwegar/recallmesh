import uuid
from dataclasses import dataclass
from .store import GraphStore


@dataclass
class AgentContext:
    tenant: str
    user_id: str


class MemoryRetrievalAgent:
    name = "memory_retriever"
    def __init__(self, store): self.store = store
    def run(self, ctx, text): return self.store.search_memories(ctx.tenant, ctx.user_id, text)


class ResearchSpecialist:
    name = "researcher"
    def __init__(self, store): self.store = store
    def run(self, ctx, task_id, title):
        result = f"Rule-based specialist completed: {title}"
        self.store.handoff(ctx.tenant, task_id, "coordinator", self.name, "completed", result)
        self.store.save_memory(ctx.tenant, ctx.user_id, self.name, "procedural", result, f"task_{task_id}", "task_result")
        return result


class CoordinatorAgent:
    name = "coordinator"
    def __init__(self, store):
        self.store = store
        self.retriever = MemoryRetrievalAgent(store)
        self.specialist = ResearchSpecialist(store)
    def handle(self, ctx, text):
        found = self.retriever.run(ctx, text)
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        self.store.create_task(ctx.tenant, ctx.user_id, task_id, text, self.specialist.name)
        result = self.specialist.run(ctx, task_id, text)
        return {"task_id": task_id, "memories": found, "result": result}

