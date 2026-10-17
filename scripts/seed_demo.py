"""Seed only the synthetic acme-demo workspace; safe to repeat."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.graph_store import GraphStore

DEMO_TENANT = "acme-demo"


def reset_demo(store: GraphStore) -> None:
    # This is deliberately scoped to the fixed synthetic demo graph.
    store.query(DEMO_TENANT, "MATCH (n) DETACH DELETE n")


def seed_demo(store: GraphStore) -> None:
    store.initialize_schema(DEMO_TENANT)
    store.create_session(DEMO_TENANT, "session_demo", "maya")
    for memory_id, user_id, scope, memory_type, content, confidence, fact_key in (
        ("demo_stack", "maya", "personal", "semantic", "My preferred stack is Python, FastAPI and FalkorDB.", .98, "preferred_stack"),
        ("demo_release", "maya", "shared", "procedural", "Our release process is to run tests, build the image, obtain QA approval, deploy and verify health.", .96, "release_process"),
        ("demo_episodic", "maya", "personal", "episodic", "Maya completed the RecallMesh demo setup.", .9, "demo_setup"),
    ):
        store.query(DEMO_TENANT, """MERGE (m:Memory {memory_id:$memory_id}) SET
            m.user_id=$user_id, m.scope=$scope, m.memory_type=$memory_type,
            m.content=$content, m.confidence=$confidence, m.active=true,
            m.version=1, m.fact_key=$fact_key, m.created_at=$now, m.updated_at=$now""", {"memory_id": memory_id, "user_id": user_id, "scope": scope, "memory_type": memory_type, "content": content, "confidence": confidence, "fact_key": fact_key, "now": store._now()})
    store.query(DEMO_TENANT, """MERGE (t:Turn {turn_id:$turn_id}) SET t.role=$role, t.content=$content, t.agent_id=$agent_id, t.timestamp=$now
        WITH t MATCH (s:Session {session_id:$session_id}) MERGE (s)-[:HAS_TURN]->(t)""", {"session_id": "session_demo", "turn_id": "turn_demo_user", "role": "user", "content": "My preferred stack is Python, FastAPI and FalkorDB.", "agent_id": "user", "now": store._now()})
    store.query(DEMO_TENANT, """MERGE (t:Turn {turn_id:$turn_id}) SET t.role=$role, t.content=$content, t.agent_id=$agent_id, t.timestamp=$now
        WITH t MATCH (s:Session {session_id:$session_id}) MERGE (s)-[:HAS_TURN]->(t)""", {"session_id": "session_demo", "turn_id": "turn_demo_assistant", "role": "assistant", "content": "Stored as semantic memory in FalkorDB.", "agent_id": "coordinator", "now": store._now()})
    print(f"Seeded synthetic workspace graph: {store.settings.graph_prefix}_{DEMO_TENANT}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the RecallMesh synthetic demo workspace")
    parser.add_argument("--reset", action="store_true", help="clear only recallmesh_acme-demo before seeding")
    args = parser.parse_args()
    store = GraphStore()
    ok, message = store.connection_test()
    if not ok:
        raise SystemExit(message)
    if args.reset:
        reset_demo(store)
        print(f"Reset synthetic workspace: {store.settings.graph_prefix}_{DEMO_TENANT}")
    seed_demo(store)


if __name__ == "__main__":
    main()
