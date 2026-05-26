"""
ObservabilityFramework — Core
==============================
Wires together OTel and OpenSearch into one object.

What gets captured automatically:
    - Full trace tree per pipeline run (visible in OpenSearch Agent Traces UI)
    - Per-agent spans with gen_ai.* attributes (Agent/LLM/Tool colored boxes)
    - Raw LLM docs indexed to OpenSearch (for log-style queries)
    - Real cost calculation per LLM call
"""

import os
import logging
from contextlib import contextmanager
from typing import Dict, Optional

from .otel import OTelSetup
from .opensearch_client import OpenSearchClient

logger = logging.getLogger("observability.core")

# ── Real cost pricing table ────────────────────────────────────────────────
# Format: model_substring → (input_cost_per_1k, output_cost_per_1k) in USD
_PRICING: list[tuple[str, float, float]] = [
    # OpenAI
    ("gpt-4o-mini",          0.000150, 0.000600),
    ("gpt-4o",               0.002500, 0.010000),
    ("gpt-4-turbo",          0.010000, 0.030000),
    ("gpt-4",                0.030000, 0.060000),
    ("gpt-3.5-turbo",        0.000500, 0.001500),
    # Anthropic
    ("claude-3-5-sonnet",    0.003000, 0.015000),
    ("claude-3-5-haiku",     0.000800, 0.004000),
    ("claude-3-opus",        0.015000, 0.075000),
    ("claude-3-sonnet",      0.003000, 0.015000),
    ("claude-3-haiku",       0.000250, 0.001250),
    # Groq
    ("llama-3.3-70b",        0.000590, 0.000790),
    ("llama-3.1-70b",        0.000590, 0.000790),
    ("llama-3.1-8b",         0.000050, 0.000080),
    ("llama-3-70b",          0.000590, 0.000790),
    ("llama-3-8b",           0.000050, 0.000080),
    ("mixtral-8x7b",         0.000240, 0.000240),
    ("gemma2-9b",            0.000200, 0.000200),
    ("gemma-7b",             0.000100, 0.000100),
]


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    model_lower = model.lower()
    for substring, input_rate, output_rate in _PRICING:
        if substring in model_lower:
            return round(
                (input_tokens  / 1000) * input_rate +
                (output_tokens / 1000) * output_rate,
                8
            )
    logger.debug("No pricing found for model '%s' — cost recorded as 0.0", model)
    return 0.0


class ObservabilityFramework:
    def __init__(self, project: str, model: str):
        self.project   = project
        self.model     = model
        self.otel      = OTelSetup(project=project)
        self.os_client = OpenSearchClient(project=project)

    def start(self):
        dashboards   = os.getenv("OPENSEARCH_DASHBOARDS_URL", "http://localhost:5601").rstrip("/")
        workspace_id = os.getenv("OPENSEARCH_WORKSPACE_ID", "")
        opensearch   = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
        traces_url   = (
            f"{dashboards}/w/{workspace_id}/app/agentTraces"
            if workspace_id else
            f"{dashboards}/app/agentTraces"
        )

        print(f"[Observability] ✅ project='{self.project}'  model='{self.model}'")
        print(f"[Observability]    OpenSearch   → {opensearch}")
        print(f"[Observability]    Agent Traces → {traces_url}")

    # ── Pipeline root span ──────────────────────────────────────────────────

    @contextmanager
    def pipeline_trace(self, trace_id: str, alert: str, severity: str = ""):
        with self.otel.root_span(
            "pipeline.run",
            attributes={
                "trace.id":          trace_id,
                "pipeline.alert":    alert,
                "pipeline.severity": severity,
                "gen_ai.system":     os.getenv("LLM_PROVIDER", "groq"),
                "gen_ai.model":      self.model,
                "service.name":      self.project,
            }
        ) as root_span:
            yield root_span

    # ── Per-agent span ──────────────────────────────────────────────────────

    def trace_agent(
        self,
        agent_name:   str,
        trace_id:     str,
        prompt:       str,
        response:     str,
        ttft:         float,
        itl:          float,
        duration:     float,
        token_count:  int   = 0,
        cost:         float = None,
        cache_hit:    bool  = False,
        is_escalated: bool  = False,
        eval_score:   float = None,
        user_segment: str   = "default",
        service_name: str   = None,
        metadata:     dict  = None,
        sub_spans:    dict  = None,
        otel_carrier: dict  = None,
    ):
        sub_spans    = sub_spans or {}
        service_name = service_name or self.project

        # Auto-calculate cost
        input_tokens  = token_count // 2
        output_tokens = token_count - input_tokens
        if cost is None:
            cost = _calculate_cost(self.model, input_tokens, output_tokens)

        # 1. Index to OpenSearch
        doc = {
            "project":              self.project,
            "service_name":         service_name,
            "model":                self.model,
            "agent_name":           agent_name,
            "trace_id":             trace_id,
            "prompt":               prompt,
            "response":             response,
            "ttft_seconds":         round(ttft, 4),
            "itl_ms":               round(itl * 1000, 2),
            "duration_seconds":     round(duration, 4),
            "token_count":          token_count,
            "input_tokens":         input_tokens,
            "output_tokens":        output_tokens,
            "cost_usd":             cost,
            "cache_hit":            cache_hit,
            "is_escalated":         is_escalated,
            "eval_score":           eval_score,
            "user_segment":         user_segment,
            "metadata":             metadata or {},
            "gen_ai.model":         self.model,
            "gen_ai.tokens.input":  input_tokens,
            "gen_ai.tokens.output": output_tokens,
            "gen_ai.prompt":        prompt[:2000],
            "gen_ai.response":      response[:2000],
        }
        self.os_client.index_trace(doc)

        # 2. OTel span tree
        if otel_carrier:
            parent_ctx = self._continued_agent_span(
                agent_name, otel_carrier, trace_id, ttft, duration, eval_score, service_name
            )
        else:
            parent_ctx = self.otel.agent_span(
                agent_name=agent_name,
                stage=agent_name,
                attributes={
                    "trace.id":         trace_id,
                    "llm.ttft_seconds": ttft,
                    "llm.duration":     duration,
                    "service.name":     service_name,
                },
            )

        with parent_ctx:
            if sub_spans.get("retrieval"):
                with self.otel.retrieval_span(agent_name, query=prompt[:200]):
                    pass

            tool_name = sub_spans.get("tool_call")
            if tool_name:
                with self.otel.tool_span(tool_name, agent_name,
                                         attributes={"tool.input": prompt[:200]}):
                    pass

            if sub_spans.get("reasoning"):
                with self.otel.reasoning_span(agent_name):
                    pass

            if sub_spans.get("evaluation"):
                with self.otel.evaluation_span(agent_name, eval_score=eval_score):
                    pass

            with self.otel.llm_span(
                "llm_generation",
                prompt=prompt,
                model=self.model,
                agent_name=agent_name,
                eval_score=eval_score,
                attributes={"workflow.stage": agent_name, "service.name": service_name},
            ) as llm_sp:
                llm_sp.set_attribute("gen_ai.response",            response[:1000])
                llm_sp.set_attribute("gen_ai.usage.input_tokens",  input_tokens)
                llm_sp.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                llm_sp.set_attribute("llm.ttft_seconds",           ttft)
                llm_sp.set_attribute("llm.itl_ms",                 round(itl * 1000, 2))
                llm_sp.set_attribute("llm.total_duration_seconds", duration)
                llm_sp.set_attribute("llm.cost_usd",               cost)
                llm_sp.set_attribute("llm.cache_hit",              cache_hit)

    @contextmanager
    def _continued_agent_span(
        self, agent_name: str, carrier: dict,
        trace_id: str, ttft: float, duration: float,
        eval_score: float, service_name: str
    ):
        with self.otel.continued_span(
            agent_name,
            carrier,
            attributes=self.otel._safe_attrs({
                "gen_ai.operation.name": "agent",
                "agent.name":            agent_name,
                "workflow.stage":        agent_name,
                "trace.id":              trace_id,
                "llm.ttft_seconds":      ttft,
                "llm.duration":          duration,
                "eval.score":            eval_score,
                "service.name":          service_name,
            }),
        ) as span:
            yield span

    def trace_pipeline(
        self,
        trace_id:  str,
        alert:     str,
        severity:  str,
        duration:  float,
        success:   bool = True,
    ):
        doc = {
            "project":          self.project,
            "trace_id":         trace_id,
            "alert":            alert,
            "severity":         severity,
            "duration_seconds": round(duration, 4),
            "success":          success,
        }
        self.os_client.index_pipeline(doc)

    def get_carrier(self) -> Dict[str, str]:
        return self.otel.inject_context()
