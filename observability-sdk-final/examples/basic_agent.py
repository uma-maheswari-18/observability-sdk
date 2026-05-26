"""
Basic Agent Example
===================
Minimal example showing how to add observability to any LLM agent.
Copy this pattern into your own project.
"""

import os
import uuid
import time
from dotenv import load_dotenv
from observability import init, get

load_dotenv()

# ── 1. Initialize once at startup ─────────────────────────────────────────────
init(
    project="my-agent",                          # your project name
    model=os.getenv("LLM_MODEL", "gpt-4o-mini"), # your LLM model
)


# ── 2. Simulate an LLM call ───────────────────────────────────────────────────
def call_llm(prompt: str) -> tuple[str, float, float, float, int]:
    """Replace this with your real LLM call."""
    start = time.time()
    time.sleep(0.3)                       # simulate LLM latency
    response = f"Response to: {prompt}"
    duration = time.time() - start
    ttft     = 0.15                       # measure from your streaming loop
    itl      = 0.01
    tokens   = len(prompt.split()) * 2
    return response, ttft, itl, duration, tokens


# ── 3. Wrap your pipeline ─────────────────────────────────────────────────────
def run_pipeline(user_input: str):
    obs      = get()
    trace_id = str(uuid.uuid4())

    with obs.pipeline_trace(trace_id, user_input) as root_span:
        response, ttft, itl, duration, tokens = call_llm(user_input)
        ctx           = root_span.get_span_context()
        otel_trace_id = format(ctx.trace_id, "032x")

    # ── 4. Trace the agent call ───────────────────────────────────────────────
    obs.trace_agent(
        agent_name   = "my-agent",
        trace_id     = trace_id,
        prompt       = user_input,
        response     = response,
        ttft         = ttft,
        itl          = itl,
        duration     = duration,
        token_count  = tokens,
        # cost is auto-calculated from model name
        eval_score   = 0.95,
        user_segment = "standard",
    )

    obs.trace_pipeline(
        trace_id = trace_id,
        alert    = user_input,
        severity = "P2",
        duration = duration,
        success  = True,
    )

    dashboards   = os.getenv("OPENSEARCH_DASHBOARDS_URL", "http://localhost:5601")
    workspace_id = os.getenv("OPENSEARCH_WORKSPACE_ID", "")
    traces_base  = f"{dashboards}/w/{workspace_id}/app/agentTraces" if workspace_id else f"{dashboards}/app/agentTraces"

    print(f"\n✅ Done!")
    print(f"   This trace → {traces_base}#/?traceId={otel_trace_id}")

    obs.otel.shutdown()


if __name__ == "__main__":
    run_pipeline("Why is my server down?")
