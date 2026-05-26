"""
Basic Agent Example
===================
Minimal example showing how to add observability to any LLM agent.
Copy this pattern into your own project.

Before (old way — 30+ lines):
    trace_id = uuid.uuid4()
    with obs.pipeline_trace(trace_id, prompt) as root_span:
        obs.trace_agent(agent_name=..., trace_id=..., prompt=..., ...)
        obs.trace_pipeline(...)
    obs.otel.shutdown()

After (new way — 2 lines):
    @observe(agent_name="my-agent")
    def run(prompt: str) -> str:
        return call_llm(prompt)
"""

import os
import time
from dotenv import load_dotenv
from observability import init, observe

load_dotenv()

# ── 1. Initialize once at startup ─────────────────────────────────────────────
init(
    project="my-agent",                           # your project name
    model=os.getenv("LLM_MODEL", "llama-3.1-8b-instant"),  # your LLM model
)


# ── 2. Simulate an LLM call (replace with your real LLM) ──────────────────────
def call_llm(prompt: str) -> str:
    """Replace this with your real LLM call.

    Works with any LLM:
        OpenAI:    client.chat.completions.create(...)
        Anthropic: client.messages.create(...)
        Groq:      client.chat.completions.create(...)
        Gemini:    genai.GenerativeModel(...).generate_content(...)
        LangChain: chain.invoke(...)
        CrewAI:    crew.kickoff(...)
    """
    time.sleep(0.3)  # simulated latency
    return f"Response to: {prompt}"


# ── 3. Just add @observe — everything else is automatic ───────────────────────
@observe(agent_name="my-agent")
def run(prompt: str) -> str:
    return call_llm(prompt)


# ── 4. Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run("Why is my server down?")