# Project
# observability-sdk

Production-ready LLM tracing for any AI agent — traces in OpenSearch.

```
Your Agent → OTel Collector → Data Prepper → OpenSearch → Dashboards
```

---

## Prerequisites

You need the Observability Docker stack running once on your machine.

### 1. Get the stack files

Copy these files into your project root:

```
your-project/
├── docker-compose.yml
├── config/
│   ├── opensearch_dashboards.yml
│   ├── data-prepper-pipeline.yml
│   ├── data-prepper-config.yml
│   └── otel-collector-config.yml
└── scripts/
    └── setup_observability.py
```

### 2. Start the stack

```bash
docker compose up -d
```

This starts:

| Service | Port | Purpose |
|---|---|---|
| OpenSearch | 9200 | Stores all traces |
| OpenSearch Dashboards | 5601 | Visualize traces |
| OTel Collector | 4319 | Receives spans from your agent |
| Data Prepper | 21890 | Processes spans → OpenSearch |

### 3. Run setup (once only)

```bash
python3 scripts/setup_observability.py
```

This will:
- Create the Observability workspace in Dashboards
- Fix the index template mapping
- Save your workspace ID to `.env`
- Print your trace URL

Output example:
```
✅  OBSERVABILITY STACK READY
   OpenSearch   → http://localhost:9200
   Dashboards   → http://localhost:5601
   Agent Traces → http://localhost:5601/w/{your-workspace-id}/app/agentTraces
```

> Your workspace ID is printed by `setup_observability.py` and saved to `.env` automatically.

---

## Installation

**Option A — Install from Git**
```bash
pip install git+https://github.com/uma-maheswari-18/observability-sdk.git
```

**Option B — Local install**
```bash
# Copy the observability/ folder into your project root, then:
pip install -e .
```

---

## Quick Start

### Step 1 — Add to your `.env`

```dotenv
# OTel Collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4319

# OpenSearch
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_USER=admin
OPENSEARCH_PASS=Admin@123456!

# Set by setup_observability.py automatically
OPENSEARCH_WORKSPACE_ID=
OPENSEARCH_DASHBOARDS_URL=http://localhost:5601

# Your LLM
LLM_PROVIDER=groq
LLM_MODEL=llama-3.1-8b-instant

# Environment
ENVIRONMENT=local
```

### Step 2 — Initialize in your project

```python
import os
from observability import init, observe

init(
    project="my-agent",
    model=os.getenv("LLM_MODEL", "llama-3.1-8b-instant"),
)
```

### Step 3 — Add the decorator to your function

```python
@observe(agent_name="my-agent")
def run(prompt: str) -> str:
    return call_llm(prompt)
```

That's it. No trace IDs, no manual timing, no shutdown calls — all handled automatically.

---

## Example Usage

### OpenAI

```python
import os
from openai import OpenAI
from observability import init, observe

init(project="my-project", model="gpt-4o")
client = OpenAI()

@observe(agent_name="assistant")
def ask(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

ask("Why is my server down?")
```

### Anthropic

```python
import os
import anthropic
from observability import init, observe

init(project="my-project", model="claude-3-5-sonnet")
client = anthropic.Anthropic()

@observe(agent_name="assistant")
def ask(prompt: str) -> str:
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

ask("Why is my server down?")
```

### Google Gemini

```python
import os
import google.generativeai as genai
from observability import init, observe

init(project="my-project", model="gemini-1.5-pro")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")

@observe(agent_name="assistant")
def ask(prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text

ask("Why is my server down?")
```

### Groq

```python
import os
from groq import Groq
from observability import init, observe

init(project="my-project", model="llama-3.1-8b-instant")
client = Groq()

@observe(agent_name="assistant")
def ask(prompt: str) -> str:
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

ask("Why is my server down?")
```

### Async support

```python
@observe(agent_name="async-agent")
async def ask(prompt: str) -> str:
    response = await call_llm_async(prompt)
    return response
```

---

## Supported Models (Auto Cost Tracking)

| Provider | Models |
|---|---|
| **OpenAI** | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, o1, o3-mini |
| **Anthropic** | claude-3-5-sonnet, claude-3-5-haiku, claude-3-opus, claude-3-haiku |
| **Google Gemini** | gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash |
| **Groq** | llama-3.3-70b, llama-3.1-8b, mixtral-8x7b, gemma2-9b |
| **Mistral** | mistral-large, mistral-small, codestral |
| **Cohere** | command-r-plus, command-r |
| **Ollama** | any local model — cost = $0.00 |

---

## View Your Traces

After running your agent, open:

```
http://localhost:5601/w/{your-workspace-id}/app/agentTraces
```

Filter by `service.name` to see only your project's traces.

---

## Summary — 4 Steps to Add Observability to Any Project

```bash
# 1. Start the stack
docker compose up -d
python scripts/setup_observability.py

# 2. Install the plugin
pip install git+https://github.com/uma-maheswari-18/observability-sdk.git

# 3. Initialize
from observability import init, observe
init(project="my-agent", model="gpt-4o-mini")

# 4. Decorate your function
@observe(agent_name="my-agent")
def run(prompt: str) -> str:
    return call_llm(prompt)
```

---

## Project Structure

```
observability-sdk/
├── observability/
│   ├── __init__.py           # init(), get(), observe()
│   ├── core.py               # trace_agent(), trace_pipeline(), cost tracking
│   ├── otel.py               # OTel span builder
│   ├── opensearch_client.py  # OpenSearch indexing with retry
│   └── observe.py            # @observe decorator
├── config/
│   ├── opensearch_dashboards.yml
│   ├── data-prepper-pipeline.yml
│   ├── data-prepper-config.yml
│   └── otel-collector-config.yml
├── scripts/
│   └── setup_observability.py
├── examples/
│   └── basic_agent.py
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## Troubleshooting

**Traces not showing in Dashboards**
```bash
curl -u admin:Admin@123456! "http://localhost:9200/otel-v1-apm-span-*/_count"
docker logs data-prepper --tail=20
docker logs otel-collector --tail=20
```

**Workspace not found**
```bash
python scripts/setup_observability.py
```

**Cost showing as 0.0**
Make sure you pass the actual model name (not provider) to `init()`:
```python
# ❌ Wrong
init(project="my-agent", model="groq")

# ✅ Correct
init(project="my-agent", model="llama-3.1-8b-instant")
```
