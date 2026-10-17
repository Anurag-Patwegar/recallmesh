import re
import uuid
from dataclasses import dataclass

from .coordinator import CoordinatorAgent


@dataclass
class ChatResult:
    response: str
    retrieved_memories: list[dict]
    history: list[dict]
    saved_memory: dict | None
    superseded_memory_id: str | None = None
    coordination: dict | None = None


class DeterministicChatAgent:
    """No-key fallback: keyword retrieval, simple extraction, and grounded templates."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def classify(text: str) -> list[tuple[str, str, str]]:
        memories = []
        match = re.search(r"my\s+preferred\s+([a-z ]+?)\s+is\s+(.+?)(?:\.|$)", text, re.I)
        if match:
            key = f"preferred_{re.sub(r'[^a-z0-9]+', '_', match.group(1).strip().lower()).strip('_')}"
            memories.append(("semantic", key, f"My preferred {match.group(1).strip()} is {match.group(2).strip()}."))
        process = re.search(r"(?:our\s+)?release\s+process\s+(?:requires|is|includes)\s+(.+?)(?:\.|$)", text, re.I)
        if process:
            memories.append(("procedural", "release_process", f"Our release process requires {process.group(1).strip()}."))
        return memories

    def handle(self, tenant_id, user_id, session_id, text, scope="personal", confidence=0.9) -> ChatResult:
        self.store.create_session(tenant_id, session_id, user_id)
        self.store.save_turn(tenant_id, session_id, f"turn_{uuid.uuid4().hex[:12]}", "user", text, "user")
        retrieved = self.store.retrieve_relevant_memory(tenant_id, user_id, text)
        history = self.store.get_recent_turns(tenant_id, user_id)
        extracted_memories = self.classify(text)
        saved = []
        superseded = None
        for memory_type, fact_key, extracted in extracted_memories:
            old = self.store.find_active_memory(tenant_id, user_id, fact_key)
            memory_id = f"memory_{uuid.uuid4().hex[:12]}"
            if old and old[0]["content"] != extracted:
                superseded = old[0]["memory_id"]
                saved.extend(self.store.supersede_memory(tenant_id, superseded, memory_id, user_id, scope, memory_type, extracted, confidence, fact_key))
            elif not old:
                saved.extend(self.store.create_memory(tenant_id, memory_id, user_id, scope, memory_type, extracted, confidence, fact_key))
        coordination = CoordinatorAgent(self.store).run(tenant_id, user_id, text, session_id)
        for item in retrieved:
            self.store.attach_memory_to_session(tenant_id, session_id, item["memory_id"])
        for memory_id in coordination.get("memories", []):
            self.store.attach_memory_to_session(tenant_id, session_id, memory_id["memory_id"])
        if retrieved:
            evidence = "\n".join(f"- {item['memory_type']} memory `{item['memory_id']}`: {item['content']}" for item in retrieved[:3])
            response = f"From your persisted FalkorDB memory:\n{evidence}"
        elif "preferred stack" in text.lower():
            response = "I do not have a persisted preferred stack for you yet."
        elif "release" in text.lower() or "process" in text.lower():
            response = "I do not have a persisted release process for this tenant and user yet."
        else:
            response = "I recorded your message. I will use persisted memory when it is relevant."
        self.store.save_turn(tenant_id, session_id, f"turn_{uuid.uuid4().hex[:12]}", "assistant", response, "coordinator")
        return ChatResult(response, retrieved, history, saved or None, superseded, coordination)
