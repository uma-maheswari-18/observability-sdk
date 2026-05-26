# observability-sdk

Production-ready LLM tracing for any AI agent — traces in OpenSearch.

```
Your Agent → OTel Collector → Data Prepper → OpenSearch → Dashboards
```

![Trace Tree](https://img.shields.io/badge/OpenSearch-3.6-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)

---

## What You Get

- **Full trace tree** per pipeline run in OpenSearch Dashboards
- **Per-agent spans** — Agent / LLM / Tool colored boxes
- **Real cost tracking** — auto-calculated for OpenAI, Anthropic, Groq
- **TTFT & ITL** — Time To First Token and Inter Token Latency
- **Multi-service** — 10 different agents, all in one UI

---

## Quickstart

### Step 1 — Start the observability stack

```bash
git clone https://github.com/your-org/observability-sdk.git
cd observability-sdk

# Copy your .env
cp .env.example .env

# Start OpenSearch + Dashboards + OTel Collector + Data Prepper
docker compose up -d

# Run setup once — creates workspace, saves URL to .env
python scripts/setup_observability.py
```

Output:
```
✅  OBSERVABILITY STACK READY
   Agent Traces → http://localhost:5601/w/abc123/app/agentTraces
```

### Step 2 — Install in your project

```bash
pip install git+https://github.com/your-org/observability-sdk.git
```

### Step 3 — Add 2 lines to your code

```python
from observability import init, get

init(project="my-agent", model="llama-3.1-8b-instant")
```

### Step 4 — Trace your agents

```python
obs = get()

with obs.pipeline_trace(trace_id, "user query") as root_span:
    result = run_my_pipeline()

obs.trace_agent(
    agent_name  = "my-agent",
    trace_id    = trace_id,
    prompt      = prompt,
    response    = response,
    ttft        = 0.32,
    itl         = 0.01,
    duration    = 1.45,
    token_count = 320,
    # cost is auto-calculated — no need to pass it
)
```

Open `http://localhost:5601/w/{workspace_id}/app/agentTraces` and see your traces live.

---

## Supported Models (Auto Cost Tracking)

| Provider | Models |
|---|---|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo |
| Anthropic | claude-3-5-sonnet, claude-3-5-haiku, claude-3-opus, claude-3-haiku |
| Groq | llama-3.3-70b, llama-3.1-8b, mixtral-8x7b, gemma2-9b |

---

## Docker Stack

| Service | Port | Purpose |
|---|---|---|
| OpenSearch | 9200 | Stores traces |
| OpenSearch Dashboards | 5601 | Visualize traces |
| OTel Collector | 4319 | Receives spans |
| Data Prepper | 21890 | Processes spans |

---

## Project Structure

```
observability-sdk/
├── observability/           # Plugin source code
│   ├── __init__.py          # init(), get(), configure_logging()
│   ├── core.py              # trace_agent(), trace_pipeline()
│   ├── otel.py              # OTel span builder
│   └── opensearch_client.py # OpenSearch indexing with retry
├── scripts/
│   └── setup_observability.py  # One-time setup script
├── examples/
│   └── basic_agent.py       # Minimal usage example
├── config/                  # Docker service configs
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## Full Documentation

See [OBSERVABILITY_SDK.md](OBSERVABILITY_SDK.md) for complete docs including all parameters,
troubleshooting, and multi-service setup.

---

## For Your Team

1. Clone this repo and run `docker compose up -d` once
2. Run `python scripts/setup_observability.py` once
3. In every project: `pip install git+https://github.com/your-org/observability-sdk.git`
4. Add `init(project="your-project", model="your-model")` at startup
5. All traces appear at the same Dashboards URL
