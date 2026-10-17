import os
import re
from datetime import datetime, timezone
from typing import Any

from falkordb import FalkorDB

SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,48}$")


def validate_id(value: str, label: str = "identifier") -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"Invalid {label}; use letters, numbers, _ or - only")
    return value


class GraphStore:
    """The only source of truth: every durable object is a FalkorDB graph node."""

    def __init__(self, host=None, port=None, username=None, password=None, prefix=None):
        self.prefix = validate_id(prefix or os.getenv("FALKORDB_GRAPH_PREFIX", "recallmesh"), "graph prefix")
        self.client = FalkorDB(
            host=host or os.getenv("FALKORDB_HOST", "localhost"),
            port=int(port or os.getenv("FALKORDB_PORT", "6379")),
            username=username if username is not None else os.getenv("FALKORDB_USERNAME") or None,
            password=password if password is not None else os.getenv("FALKORDB_PASSWORD") or None,
        )

    def graph(self, tenant: str):
        tenant = validate_id(tenant, "tenant")
        return self.client.select_graph(f"{self.prefix}_{tenant}")

    @staticmethod
    def _rows(result):
        return [dict(zip(result.header, row)) for row in result.result_set]

    def query(self, tenant: str, cypher: str, params: dict[str, Any] | None = None):
        return self.graph(tenant).query(cypher, params or {})

    def ensure_schema(self, tenant: str):
        for label, prop in [("Memory", "id"), ("Conversation", "id"), ("Task", "id"), ("Agent", "id")]:
            try:
                self.query(tenant, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except Exception:
                pass

    def save_memory(self, tenant, user_id, agent_id, kind, content, memory_id, source="user"):
        now = datetime.now(timezone.utc).isoformat()
        cypher = """
        MERGE (m:Memory {id: $id})
        SET m.kind=$kind, m.content=$content, m.user_id=$user_id, m.agent_id=$agent_id,
            m.source=$source, m.updated_at=$now
        MERGE (u:User {id:$user_id})
        MERGE (a:Agent {id:$agent_id})
        MERGE (u)-[:OWNS]->(m)
        MERGE (a)-[:WROTE]->(m)
        RETURN m.id AS id, m.updated_at AS updated_at
        """
        return self._rows(self.query(tenant, cypher, locals()))

    def update_memory(self, tenant, user_id, agent_id, memory_id, kind, content):
        previous = self.query(tenant, "MATCH (m:Memory {id:$id, user_id:$user_id}) RETURN m.content AS content", {"id": memory_id, "user_id": user_id})
        if not previous.result_set:
            return self.save_memory(tenant, user_id, agent_id, kind, content, memory_id)
        old_id = f"{memory_id}_v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        self.save_memory(tenant, user_id, agent_id, kind, previous.result_set[0][0], old_id, "superseded")
        result = self.save_memory(tenant, user_id, agent_id, kind, content, memory_id, "user_update")
        self.query(tenant, "MATCH (old:Memory {id:$old}), (new:Memory {id:$new}) MERGE (new)-[:SUPERSEDES]->(old)", {"old": old_id, "new": memory_id})
        return result

    def search_memories(self, tenant, user_id, text, limit=10):
        result = self.query(tenant, "MATCH (m:Memory) WHERE m.user_id=$user_id AND (toLower(m.content) CONTAINS toLower($text) OR m.kind=$text) RETURN m ORDER BY m.updated_at DESC LIMIT $limit", locals())
        return self._rows(result)

    def add_conversation(self, tenant, user_id, agent_id, role, content, conversation_id):
        return self._rows(self.query(tenant, "CREATE (c:Conversation {id:$id, user_id:$user_id, agent_id:$agent_id, role:$role, content:$content, created_at:$now}) RETURN c", {**locals(), "now": datetime.now(timezone.utc).isoformat()}))

    def conversation_history(self, tenant, user_id, limit=50):
        return self._rows(self.query(tenant, "MATCH (c:Conversation {user_id:$user_id}) RETURN c ORDER BY c.created_at DESC LIMIT $limit", locals()))

    def concurrent_demo(self, tenant, user_id):
        """Exercise independent FalkorDB read/write calls concurrently."""
        from concurrent.futures import ThreadPoolExecutor
        memory_id = f"concurrent_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            write = pool.submit(self.save_memory, tenant, user_id, "demo_writer", "episodic", "Concurrent write completed", memory_id)
            read = pool.submit(self.search_memories, tenant, user_id, "Concurrent", 10)
            return {"write": write.result(), "read": read.result(), "memory_id": memory_id}

    def create_task(self, tenant, user_id, task_id, title, specialist="researcher"):
        now = datetime.now(timezone.utc).isoformat()
        cypher = """MERGE (t:Task {id:$task_id}) SET t.title=$title, t.status='assigned', t.user_id=$user_id, t.created_at=$now
        MERGE (u:User {id:$user_id}) MERGE (a:Agent {id:$specialist}) MERGE (u)-[:REQUESTED]->(t) MERGE (t)-[:ASSIGNED_TO]->(a) RETURN t"""
        return self._rows(self.query(tenant, cypher, locals()))

    def handoff(self, tenant, task_id, from_agent, to_agent, status, result_text):
        now = datetime.now(timezone.utc).isoformat()
        cypher = """MATCH (t:Task {id:$task_id}) SET t.status=$status, t.result=$result_text, t.updated_at=$now
        MERGE (f:Agent {id:$from_agent}) MERGE (to:Agent {id:$to_agent})
        CREATE (f)-[:HANDOFF {status:$status, at:$now, result:$result_text}]->(t)-[:RECEIVED_BY]->(to) RETURN t"""
        return self._rows(self.query(tenant, cypher, locals()))

    def graph_snapshot(self, tenant):
        return self._rows(self.query(tenant, "MATCH (n) RETURN labels(n) AS labels, n.id AS id, n.status AS status, n.kind AS kind ORDER BY n.updated_at DESC LIMIT 100"))

