import html
import uuid

import streamlit as st

from agents.chat_agent import DeterministicChatAgent
from memory.graph_store import GraphStore, validate_tenant_id

st.set_page_config(page_title="RecallMesh", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {max-width: 1400px; padding-top: 2rem;}
[data-testid="stMetricValue"] {color: #55d6be;}
.hero {padding: 1.2rem 1.4rem; border: 1px solid #26384a; border-radius: 14px; background: linear-gradient(135deg,#122330,#182c3a); margin-bottom: 1rem;}
.hero h1 {margin: 0; letter-spacing: -.04em;}
.hero p {color: #9eb2c2; margin: .3rem 0 0;}
.pill {display:inline-block; padding:.25rem .65rem; border-radius:99px; background:#203646; color:#bdeee5; font-size:.8rem; margin-right:.35rem;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>◈ RecallMesh</h1><p>Persistent memory and observable multi-agent coordination, backed by FalkorDB.</p></div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Workspace")
    tenant = st.selectbox("Current workspace", ["acme-demo", "beta-demo"])
    user = st.selectbox("Demo user · logical isolation only", ["maya", "leo"])
    st.caption("This selector demonstrates tenant/user isolation; it is not production authentication.")
    view = st.radio("Navigate", ["Chat & Recall", "Memory Explorer", "Agent Coordination", "Graph View", "Isolation & Concurrency", "System Health"], label_visibility="collapsed")
    st.divider()
    st.markdown(f'<span class="pill">tenant: {tenant}</span><span class="pill">user: {user}</span>', unsafe_allow_html=True)

if st.session_state.get("active_tenant") != tenant or st.session_state.get("active_user") != user:
    st.session_state.active_tenant = tenant
    st.session_state.active_user = user
    st.session_state.session_id = f"session_{uuid.uuid4().hex[:12]}"
    st.session_state.messages = []
    st.session_state.pop("last_task_id", None)
if "session_id" not in st.session_state:
    st.session_state.session_id = f"session_{uuid.uuid4().hex[:12]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

try:
    validate_tenant_id(tenant)
    store = GraphStore()
    connected, health_message = store.connection_test()
except ValueError as exc:
    connected, health_message, store = False, str(exc), None

if not connected:
    st.error(health_message)
    st.info("Start FalkorDB with `docker run -d --name recallmesh-db -p 6379:6379 falkordb/falkordb:latest`.")
    st.stop()

store.create_session(tenant, st.session_state.session_id, user)
st.caption(f"● FalkorDB connected · `{tenant}` · `{user}` · session `{st.session_state.session_id}`")

def render_chat():
    sessions = store.list_sessions(tenant, user)
    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader("Chat & Recall")
    with c2:
        if st.button("＋ New Session", use_container_width=True):
            st.session_state.session_id = f"session_{uuid.uuid4().hex[:12]}"
            st.session_state.messages = []
            st.rerun()
    if sessions:
        labels = [item["session_id"] for item in sessions]
        selected = st.selectbox("Persistent session history", labels, index=labels.index(st.session_state.session_id) if st.session_state.session_id in labels else 0)
        if selected != st.session_state.session_id:
            st.session_state.session_id = selected
            st.session_state.messages = []
            st.rerun()
    for item in st.session_state.messages:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
    prompt = st.chat_input("Ask about your memory or workflow")
    if prompt:
        result = DeterministicChatAgent(store).handle(tenant, user, st.session_state.session_id, prompt)
        st.session_state.last_task_id = result.coordination["task_id"] if result.coordination else None
        st.session_state.messages.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": result.response}])
        st.rerun()
    st.subheader("Memories used by the answer")
    if len(st.session_state.messages) >= 2:
        used = store.retrieve_relevant_memory(tenant, user, st.session_state.messages[-2]["content"])
        if used:
            for item in used:
                st.info(f"**{item['memory_type']}** · **{item['scope']}** · source: FalkorDB Memory node `{item['memory_id']}` · relevance {item['relevance']}\n\n{item['content']}")
        else:
            st.caption("No matching persistent memory was retrieved for the latest question.")
    else:
        st.caption("Start a conversation. Retrieved source memories will appear here.")
    st.subheader("Persistent conversation")
    st.dataframe(store.get_recent_turns(tenant, user, 20), use_container_width=True, hide_index=True)
    if st.session_state.get("last_task_id"):
        st.subheader("Coordination timeline · persisted graph events")
        st.dataframe(store.coordination_timeline(tenant, st.session_state.last_task_id), use_container_width=True, hide_index=True)

def render_memory_explorer():
    st.subheader("Memory Explorer")
    st.caption("Only active memories visible to the selected user in the selected tenant graph are shown.")
    c1, c2 = st.columns([3, 1])
    search = c1.text_input("Search memory content", placeholder="e.g. release, Python, preferred")
    kind = c2.selectbox("Type", ["All", "episodic", "semantic", "procedural"])
    records = store.search_memories(tenant, user, search, None if kind == "All" else kind)
    if records:
        st.dataframe(records, use_container_width=True, hide_index=True)
    else:
        st.info("No memories match this tenant, user, and filter.")
    st.divider()
    st.markdown("#### Add synthetic demo knowledge")
    with st.form("memory_form"):
        memory_type = st.selectbox("Memory type", ["episodic", "semantic", "procedural"])
        scope = st.selectbox("Scope", ["personal", "shared"])
        confidence = st.slider("Confidence", 0.0, 1.0, .9, .05)
        content = st.text_area("Content")
        if st.form_submit_button("Persist memory") and content:
            store.create_memory(tenant, f"memory_{uuid.uuid4().hex[:12]}", user, scope, memory_type, content, confidence)
            st.success("Persisted to FalkorDB.")

def render_coordination():
    st.subheader("Agent Coordination")
    records = store.coordination_records(tenant, user)
    if not records:
        st.info("No tasks or handoffs yet. Ask a question in Chat & Recall to create one.")
        return
    for record in records:
        with st.expander(f"{record['task_id']} · {record['status']} · {record['description']}", expanded=False):
            st.write(f"**Source:** {record['source_agent'] or '—'}  →  **Destination:** {record['destination_agent'] or '—'}")
            st.write(f"**Handoff:** `{record['handoff_id'] or '—'}` · {record['handoff_status'] or '—'}")
            st.write("**Context:**", record["handoff_context"] or "—")
            st.write("**Result:**", record["handoff_result"] or record["task_result"] or "—")
            st.caption(f"Created {record['created_at']}")

def render_graph():
    st.subheader("Graph View")
    records, relationships = store.list_graph_records(tenant), store.list_graph_relationships(tenant)
    if not records:
        st.info("This tenant graph has no records yet.")
        return
    node_map = {}
    lines = ["digraph RecallMesh {", "rankdir=LR;", "node [shape=box style=filled fontname=Arial];"]
    for index, record in enumerate(records[:100]):
        props = record["properties"] or {}
        key = next((props.get(name) for name in ("memory_id", "task_id", "handoff_id", "session_id", "agent_id", "turn_id", "event_id")), f"node_{index}")
        node_id = f"n{index}"
        node_map[str(key)] = node_id
        label = f"{record['labels'][0]}\\n{str(key)[:28]}"
        lines.append(f'{node_id} [label="{html.escape(label).replace(chr(34), chr(92)+chr(34))}"];')
    for rel in relationships[:200]:
        source = next((rel["from_properties"].get(name) for name in ("memory_id", "task_id", "handoff_id", "session_id", "agent_id", "turn_id", "event_id") if rel["from_properties"] and rel["from_properties"].get(name)), None)
        target = next((rel["to_properties"].get(name) for name in ("memory_id", "task_id", "handoff_id", "session_id", "agent_id", "turn_id", "event_id") if rel["to_properties"] and rel["to_properties"].get(name)), None)
        if str(source) in node_map and str(target) in node_map:
            lines.append(f'{node_map[str(source)]} -> {node_map[str(target)]} [label="{rel["relationship"]}"];')
    lines.append("}")
    st.graphviz_chart("\n".join(lines), use_container_width=True)
    st.caption(f"Rendered from {len(records)} FalkorDB nodes and {len(relationships)} FalkorDB relationships.")

def render_isolation():
    st.subheader("Isolation & Concurrency")
    st.write(f"Current graph: `recallmesh_{tenant}`")
    st.info("Switch workspace or demo user in the sidebar. The UI resets its visible session, while FalkorDB data remains isolated by graph and user scope.")
    if st.button("Run Concurrent Memory Test"):
        with st.spinner("Writing and reading 20 records through FalkorDB..."):
            result = store.run_concurrent_memory_test(tenant, user, count=20, workers=5)
        st.json(result)
        (st.success if result["verification_passed"] else st.error)("All concurrent operations verified." if result["verification_passed"] else "Concurrent test had failures; inspect failed_operations.")

def render_health():
    st.subheader("System Health")
    ok, message = store.connection_test()
    st.success(message) if ok else st.error(message)
    counts = store.record_counts(tenant)
    cols = st.columns(4)
    for col, (label, value) in zip(cols * 2, counts.items()):
        col.metric(label, value)
    st.caption("Counts are live FalkorDB queries for the selected tenant graph.")

{"Chat & Recall": render_chat, "Memory Explorer": render_memory_explorer, "Agent Coordination": render_coordination, "Graph View": render_graph, "Isolation & Concurrency": render_isolation, "System Health": render_health}[view]()
