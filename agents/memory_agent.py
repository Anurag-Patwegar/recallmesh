class MemoryAgent:
    def __init__(self, store): self.store = store
    def retrieve(self, tenant_id, user_id, text):
        return self.store.retrieve_relevant_memory(tenant_id, user_id, text)

    def propose(self, tenant_id, user_id, text):
        return {"memory_ids": [item["memory_id"] for item in self.retrieve(tenant_id, user_id, text)]}
