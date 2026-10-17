import re
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from falkordb import FalkorDB
from .schema import MEMORY_SCOPES, MEMORY_TYPES, Settings, schema_queries

SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,48}$")

def validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not SAFE_ID.fullmatch(tenant_id):
        raise ValueError("Invalid tenant ID; use 1-49 letters, numbers, hyphens or underscores")
    return tenant_id

class GraphStore:
    """Reusable FalkorDB client; durable application state belongs in FalkorDB."""
    def __init__(self, settings: Settings | None = None, client: Any | None = None):
        self.settings = settings or Settings()
        self.client = client or FalkorDB(host=self.settings.falkordb_host, port=self.settings.falkordb_port, username=self.settings.falkordb_username, password=self.settings.falkordb_password)

    def select_tenant_graph(self, tenant_id: str):
        return self.client.select_graph(f"{self.settings.graph_prefix}_{validate_tenant_id(tenant_id)}")

    def connection_test(self) -> tuple[bool, str]:
        try:
            self.select_tenant_graph("healthcheck").query("RETURN 1 AS connected")
            return True, f"Connected to FalkorDB at {self.settings.falkordb_host}:{self.settings.falkordb_port}"
        except Exception as exc:
            return False, f"FalkorDB unavailable at {self.settings.falkordb_host}:{self.settings.falkordb_port}: {exc}"

    def initialize_schema(self, tenant_id: str) -> None:
        graph = self.select_tenant_graph(tenant_id)
        for query in schema_queries():
            try:
                graph.query(query)
            except Exception:
                pass

    def query(self, tenant_id: str, cypher: str, params: dict[str, Any] | None = None):
        return self.select_tenant_graph(tenant_id).query(cypher, params or {})

    @staticmethod
    def rows(result) -> list[dict[str, Any]]:
        headers = [item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item for item in result.header]
        return [dict(zip(headers, row)) for row in result.result_set]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_session(self, tenant_id, session_id, user_id, created_at=None):
        return self.rows(self.query(tenant_id, "MERGE (s:Session {session_id:$session_id}) SET s.user_id=$user_id, s.created_at=$created_at RETURN s", {"session_id": session_id, "user_id": user_id, "created_at": created_at or self._now()}))

    def get_session(self, tenant_id, session_id, user_id=None):
        query = "MATCH (s:Session {session_id:$session_id}) WHERE $user_id IS NULL OR s.user_id=$user_id RETURN s"
        return self.rows(self.query(tenant_id, query, {"session_id": session_id, "user_id": user_id}))

    def list_sessions(self, tenant_id, user_id, limit=50):
        return self.rows(self.query(tenant_id, "MATCH (s:Session {user_id:$user_id}) RETURN s.session_id AS session_id, s.created_at AS created_at ORDER BY s.created_at DESC LIMIT $limit", {"user_id": user_id, "limit": limit}))

    def save_turn(self, tenant_id, session_id, turn_id, role, content, agent_id=None, timestamp=None):
        query = """MATCH (s:Session {session_id:$session_id})
        CREATE (t:Turn {turn_id:$turn_id, role:$role, content:$content, timestamp:$timestamp, agent_id:$agent_id})
        CREATE (s)-[:HAS_TURN]->(t) RETURN t"""
        return self.rows(self.query(tenant_id, query, {"session_id": session_id, "turn_id": turn_id, "role": role, "content": content, "agent_id": agent_id, "timestamp": timestamp or self._now()}))

    def get_turns(self, tenant_id, session_id):
        return self.rows(self.query(tenant_id, "MATCH (:Session {session_id:$session_id})-[:HAS_TURN]->(t:Turn) RETURN t ORDER BY t.timestamp", {"session_id": session_id}))

    def create_memory(self, tenant_id, memory_id, user_id, scope, memory_type, content, confidence=1.0, fact_key=None):
        if scope not in MEMORY_SCOPES or memory_type not in MEMORY_TYPES:
            raise ValueError("scope must be personal/shared and memory_type must be episodic/semantic/procedural")
        now = self._now()
        query = """CREATE (m:Memory {memory_id:$memory_id, user_id:$user_id, scope:$scope,
        memory_type:$memory_type, content:$content, confidence:$confidence, active:true,
        version:1, fact_key:$fact_key, created_at:$now, updated_at:$now})
        RETURN m.memory_id AS memory_id, m.user_id AS user_id, m.scope AS scope,
        m.memory_type AS memory_type, m.content AS content, m.confidence AS confidence,
        m.active AS active, m.version AS version, m.fact_key AS fact_key"""
        return self.rows(self.query(tenant_id, query, {"memory_id": memory_id, "user_id": user_id, "scope": scope, "memory_type": memory_type, "content": content, "confidence": confidence, "fact_key": fact_key, "now": now}))

    def retrieve_relevant_memory(self, tenant_id, user_id, text, limit=10):
        query = """MATCH (m:Memory) WHERE m.active=true AND (m.scope='shared' OR m.user_id=$user_id)
        RETURN m.memory_id AS memory_id, m.user_id AS user_id, m.scope AS scope,
        m.memory_type AS memory_type, m.content AS content, m.confidence AS confidence,
        m.version AS version, m.updated_at AS updated_at, m.fact_key AS fact_key"""
        candidates = self.rows(self.query(tenant_id, query, {"user_id": user_id}))
        terms = {term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2}
        for item in candidates:
            words = set(re.findall(r"[a-z0-9]+", str(item.get("content", "")).lower()))
            item["relevance"] = len(terms & words)
        return sorted((item for item in candidates if item["relevance"] > 0), key=lambda item: (item["relevance"], item.get("confidence") or 0, item.get("updated_at") or ""), reverse=True)[:limit]

    def retrieve_shared_memory(self, tenant_id, user_id, memory_type=None, limit=50):
        query = """MATCH (m:Memory) WHERE m.active=true AND m.scope='shared'
        AND ($memory_type IS NULL OR m.memory_type=$memory_type)
        RETURN m ORDER BY m.updated_at DESC LIMIT $limit"""
        return self.rows(self.query(tenant_id, query, {"user_id": user_id, "memory_type": memory_type, "limit": limit}))

    def supersede_memory(self, tenant_id, previous_memory_id, new_memory_id, user_id, scope, memory_type, content, confidence=1.0, fact_key=None):
        created = self.create_memory(tenant_id, new_memory_id, user_id, scope, memory_type, content, confidence, fact_key)
        query = """MATCH (old:Memory {memory_id:$old_id}), (new:Memory {memory_id:$new_id})
        SET old.active=false, new.version=old.version+1
        CREATE (new)-[:SUPERSEDES]->(old) RETURN new"""
        self.query(tenant_id, query, {"old_id": previous_memory_id, "new_id": new_memory_id})
        return created

    def find_active_memory(self, tenant_id, user_id, fact_key):
        return self.rows(self.query(tenant_id, "MATCH (m:Memory) WHERE m.active=true AND m.user_id=$user_id AND m.fact_key=$fact_key RETURN m.memory_id AS memory_id, m.content AS content, m.version AS version", {"user_id": user_id, "fact_key": fact_key}))

    def get_recent_turns(self, tenant_id, user_id, limit=12):
        return self.rows(self.query(tenant_id, "MATCH (s:Session {user_id:$user_id})-[:HAS_TURN]->(t:Turn) RETURN t.turn_id AS turn_id, t.role AS role, t.content AS content, t.timestamp AS timestamp, t.agent_id AS agent_id ORDER BY t.timestamp DESC LIMIT $limit", {"user_id": user_id, "limit": limit}))

    def create_task(self, tenant_id, task_id, description, status="pending", created_at=None, user_id=None):
        now = created_at or self._now()
        return self.rows(self.query(tenant_id, "CREATE (t:Task {task_id:$task_id, description:$description, status:$status, user_id:$user_id, created_at:$now, updated_at:$now, status_updated_at:$now}) RETURN t.task_id AS task_id, t.status AS status", {"task_id": task_id, "description": description, "status": status, "user_id": user_id, "now": now}))

    def update_task(self, tenant_id, task_id, status, description=None):
        return self.rows(self.query(tenant_id, "MATCH (t:Task {task_id:$task_id}) SET t.status=$status, t.description=coalesce($description,t.description), t.updated_at=$now, t.status_updated_at=$now RETURN t.task_id AS task_id, t.status AS status, t.result AS result, t.error AS error", {"task_id": task_id, "status": status, "description": description, "now": self._now()}))

    def assign_task(self, tenant_id, task_id, agent_id, agent_name, agent_role):
        query = """MATCH (t:Task {task_id:$task_id})
        MERGE (a:Agent {agent_id:$agent_id}) SET a.name=$agent_name, a.role=$agent_role
        CREATE (t)-[:ASSIGNED_TO]->(a) RETURN a.agent_id AS agent_id"""
        return self.rows(self.query(tenant_id, query, {"task_id": task_id, "agent_id": agent_id, "agent_name": agent_name, "agent_role": agent_role}))

    def create_handoff(self, tenant_id, handoff_id, task_id, from_agent_id, to_agent_id, payload, memory_ids=None, status="pending"):
        query = """MATCH (t:Task {task_id:$task_id})
        MERGE (source:Agent {agent_id:$from_agent_id}) MERGE (target:Agent {agent_id:$to_agent_id})
        CREATE (h:Handoff {handoff_id:$handoff_id, task_id:$task_id, source_agent_id:$from_agent_id, destination_agent_id:$to_agent_id, status:$status, payload:$payload, memory_ids:$memory_ids, created_at:$now, status_updated_at:$now, completed_at:null, result:null, error:null})
        CREATE (t)-[:HAS_HANDOFF]->(h)-[:FROM_AGENT]->(source)
        CREATE (h)-[:TO_AGENT]->(target) RETURN h"""
        return self.rows(self.query(tenant_id, query, {"handoff_id": handoff_id, "task_id": task_id, "from_agent_id": from_agent_id, "to_agent_id": to_agent_id, "payload": payload, "memory_ids": memory_ids or [], "status": status, "now": self._now()}))

    def update_handoff(self, tenant_id, handoff_id, status, payload=None, result=None, error=None):
        completed = self._now() if status == "completed" else None
        return self.rows(self.query(tenant_id, "MATCH (h:Handoff {handoff_id:$handoff_id}) SET h.status=$status, h.payload=coalesce($payload,h.payload), h.result=coalesce($result,h.result), h.error=coalesce($error,h.error), h.completed_at=$completed, h.status_updated_at=$now RETURN h.handoff_id AS handoff_id, h.status AS status, h.result AS result, h.error AS error", {"handoff_id": handoff_id, "status": status, "payload": payload, "result": result, "error": error, "completed": completed, "now": self._now()}))

    def set_task_result(self, tenant_id, task_id, status, result=None, error=None):
        return self.rows(self.query(tenant_id, "MATCH (t:Task {task_id:$task_id}) SET t.status=$status, t.result=$result, t.error=$error, t.updated_at=$now, t.status_updated_at=$now RETURN t.task_id AS task_id, t.status AS status, t.result AS result, t.error AS error", {"task_id": task_id, "status": status, "result": result, "error": error, "now": self._now()}))

    def coordination_timeline(self, tenant_id, task_id):
        events = self.rows(self.query(tenant_id, "MATCH (t:Task {task_id:$task_id}) RETURN 'task' AS event_type, t.task_id AS record_id, t.status AS status, t.status_updated_at AS at, t.description AS detail, t.result AS result", {"task_id": task_id}))
        events += self.rows(self.query(tenant_id, "MATCH (t:Task {task_id:$task_id})-[:HAS_HANDOFF]->(h:Handoff) RETURN 'handoff' AS event_type, h.handoff_id AS record_id, h.status AS status, h.status_updated_at AS at, h.payload AS detail, h.result AS result", {"task_id": task_id}))
        events += self.rows(self.query(tenant_id, "MATCH (t:Task {task_id:$task_id})-[:HAS_EVENT]->(e:CoordinationEvent) RETURN 'event' AS event_type, e.event_id AS record_id, e.status AS status, e.at AS at, e.stage AS detail, e.result AS result", {"task_id": task_id}))
        return sorted(events, key=lambda event: event.get("at") or "")

    def record_coordination_event(self, tenant_id, task_id, stage, status, detail=None, result=None):
        query = """MATCH (t:Task {task_id:$task_id})
        CREATE (e:CoordinationEvent {event_id:$event_id, stage:$stage, status:$status, detail:$detail, result:$result, at:$at})
        CREATE (t)-[:HAS_EVENT]->(e) RETURN e.event_id AS event_id"""
        return self.rows(self.query(tenant_id, query, {"task_id": task_id, "event_id": f"event_{uuid.uuid4().hex[:12]}", "stage": stage, "status": status, "detail": detail, "result": result, "at": self._now()}))

    def attach_memory_to_session(self, tenant_id, session_id, memory_id):
        return self.rows(self.query(tenant_id, "MATCH (s:Session {session_id:$session_id}), (m:Memory {memory_id:$memory_id}) CREATE (s)-[:HAS_MEMORY]->(m) RETURN m", {"session_id": session_id, "memory_id": memory_id}))

    def attach_memory_to_task(self, tenant_id, task_id, memory_id):
        return self.rows(self.query(tenant_id, "MATCH (t:Task {task_id:$task_id}), (m:Memory {memory_id:$memory_id}) CREATE (t)-[:USES_MEMORY]->(m) RETURN m", {"task_id": task_id, "memory_id": memory_id}))

    def list_graph_records(self, tenant_id):
        return self.rows(self.query(tenant_id, "MATCH (n) RETURN labels(n) AS labels, properties(n) AS properties ORDER BY labels(n)[0]"))

    def list_graph_relationships(self, tenant_id):
        return self.rows(self.query(tenant_id, "MATCH (a)-[r]->(b) RETURN labels(a) AS from_labels, properties(a) AS from_properties, type(r) AS relationship, labels(b) AS to_labels, properties(b) AS to_properties"))

    def search_memories(self, tenant_id, user_id, search="", memory_type=None, limit=100):
        query = """MATCH (m:Memory) WHERE m.active=true AND (m.scope='shared' OR m.user_id=$user_id)
        AND ($search='' OR toLower(m.content) CONTAINS toLower($search))
        AND ($memory_type IS NULL OR m.memory_type=$memory_type)
        RETURN m.memory_id AS memory_id, m.user_id AS user_id, m.scope AS scope,
        m.memory_type AS memory_type, m.content AS content, m.confidence AS confidence,
        m.version AS version, m.updated_at AS updated_at ORDER BY m.updated_at DESC LIMIT $limit"""
        return self.rows(self.query(tenant_id, query, {"user_id": user_id, "search": search, "memory_type": memory_type, "limit": limit}))

    def coordination_records(self, tenant_id, user_id=None, limit=100):
        query = """MATCH (t:Task) WHERE $user_id IS NULL OR t.user_id=$user_id
        OPTIONAL MATCH (t)-[:HAS_HANDOFF]->(h:Handoff)
        RETURN t.task_id AS task_id, t.description AS description, t.status AS status,
        t.result AS task_result, t.created_at AS created_at, h.handoff_id AS handoff_id,
        h.source_agent_id AS source_agent, h.destination_agent_id AS destination_agent,
        h.payload AS handoff_context, h.status AS handoff_status, h.result AS handoff_result
        ORDER BY t.created_at DESC LIMIT $limit"""
        return self.rows(self.query(tenant_id, query, {"user_id": user_id, "limit": limit}))

    def record_counts(self, tenant_id):
        counts = {}
        for label in ("Session", "Turn", "Memory", "Agent", "Task", "Handoff", "CoordinationEvent"):
            result = self.query(tenant_id, f"MATCH (n:{label}) RETURN count(n) AS count")
            counts[label] = self.rows(result)[0]["count"]
        relationship_result = self.query(tenant_id, "MATCH ()-[r]->() RETURN count(r) AS count")
        counts["Relationships"] = self.rows(relationship_result)[0]["count"]
        return counts

    def run_concurrent_memory_test(self, tenant_id, user_id, count=20, workers=5):
        """Write and read independent records through FalkorDB's client pool."""
        records = [(f"concurrent_{uuid.uuid4().hex}", f"Concurrent memory {uuid.uuid4().hex}") for _ in range(count)]

        def write(record):
            memory_id, content = record
            return self.create_memory(tenant_id, memory_id, user_id, "personal", "episodic", content, 1.0)

        successful_writes, failures = [], []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(write, record): record for record in records}
            for future in as_completed(futures):
                record = futures[future]
                try:
                    future.result()
                    successful_writes.append(record[0])
                except Exception as exc:
                    failures.append({"operation": "write", "memory_id": record[0], "error": str(exc)})

        def read(memory_id):
            result = self.query(tenant_id, "MATCH (m:Memory {memory_id:$memory_id}) WHERE m.user_id=$user_id AND m.active=true RETURN m.memory_id AS memory_id", {"memory_id": memory_id, "user_id": user_id})
            return bool(result.result_set)

        verified, read_failures = [], []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(read, memory_id): memory_id for memory_id in successful_writes}
            for future in as_completed(futures):
                memory_id = futures[future]
                try:
                    if future.result():
                        verified.append(memory_id)
                    else:
                        read_failures.append({"operation": "read", "memory_id": memory_id, "error": "record not found"})
                except Exception as exc:
                    read_failures.append({"operation": "read", "memory_id": memory_id, "error": str(exc)})
        failures.extend(read_failures)
        return {"attempted_writes": count, "successful_writes": len(successful_writes), "attempted_reads": len(successful_writes), "successful_reads": len(verified), "failed_operations": failures, "verified_memory_ids": sorted(verified), "verification_passed": len(verified) == len(successful_writes) and not failures}
