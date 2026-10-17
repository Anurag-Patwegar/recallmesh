import uuid

from .memory_agent import MemoryAgent
from .specialist_agent import SpecialistAgent


class CoordinatorAgent:
    name = "coordinator"
    role = "Coordinator Agent"

    def __init__(self, store):
        self.store = store
        self.memory_agent = MemoryAgent(store)
        self.specialist = SpecialistAgent(store)

    @staticmethod
    def route(request: str) -> tuple[str, str]:
        lowered = request.lower()
        if any(word in lowered for word in ("deploy", "release", "workflow", "process", "project", "pipeline", "qa")):
            return "workflow_specialist", "Workflow Specialist"
        return "workflow_specialist", "Workflow Specialist"

    def run(self, tenant_id, user_id, request, session_id=None):
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        handoff_id = f"handoff_{uuid.uuid4().hex[:12]}"
        timeline = []
        try:
            memories = self.memory_agent.retrieve(tenant_id, user_id, request)
            timeline.append({"stage": "memory_retrieved", "memory_ids": [item["memory_id"] for item in memories]})
            self.store.create_task(tenant_id, task_id, request, "pending", user_id=user_id)
            self.store.record_coordination_event(tenant_id, task_id, "task_created", "pending", request)
            self.store.update_task(tenant_id, task_id, "in_progress")
            self.store.record_coordination_event(tenant_id, task_id, "task_started", "in_progress")
            timeline.append({"stage": "task_created", "task_id": task_id, "status": "in_progress"})
            agent_id, agent_name = self.route(request)
            memory_ids = [item["memory_id"] for item in memories]
            payload = f"Task: {request}\nMemory references: {', '.join(memory_ids) or 'none'}"
            self.store.create_handoff(tenant_id, handoff_id, task_id, self.name, agent_id, payload, memory_ids)
            self.store.assign_task(tenant_id, task_id, agent_id, agent_name, self.specialist.role)
            for memory_id in memory_ids:
                self.store.attach_memory_to_task(tenant_id, task_id, memory_id)
            self.store.record_coordination_event(tenant_id, task_id, "handoff_assigned", "pending", payload)
            timeline.append({"stage": "handoff_assigned", "handoff_id": handoff_id, "agent": agent_name, "memory_ids": memory_ids})
            result = self.specialist.execute(tenant_id, task_id, handoff_id, request)
            self.store.record_coordination_event(tenant_id, task_id, "specialist_completed", "completed", result, result)
            timeline.append({"stage": "specialist_completed", "status": "completed", "result": result})
            return {"task_id": task_id, "handoff_id": handoff_id, "result": result, "memories": memories, "timeline": timeline}
        except Exception as exc:
            error = str(exc)
            self.store.set_task_result(tenant_id, task_id, "failed", error=error)
            self.store.update_handoff(tenant_id, handoff_id, "failed", error=error)
            self.store.record_coordination_event(tenant_id, task_id, "failed", "failed", error, error)
            timeline.append({"stage": "failed", "status": "failed", "error": error})
            return {"task_id": task_id, "handoff_id": handoff_id, "result": "The coordination task failed.", "memories": [], "timeline": timeline, "error": error}
