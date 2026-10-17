class SpecialistAgent:
    name = "workflow_specialist"
    role = "Workflow Specialist"
    def __init__(self, store): self.store = store
    def execute(self, tenant_id, task_id, handoff_id, title):
        self.store.update_handoff(tenant_id, handoff_id, "in_progress")
        result = f"Workflow Specialist completed: {title}"
        self.store.update_handoff(tenant_id, handoff_id, "completed", result=result)
        self.store.set_task_result(tenant_id, task_id, "completed", result=result)
        return result
