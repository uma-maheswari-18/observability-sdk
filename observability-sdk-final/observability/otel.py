"""
OTel Setup
==========
Configures OpenTelemetry SDK to send spans to OTel Collector.

Pipeline:
    Your Agent (Python)
        → OTel Collector (OTLP HTTP)
            → Data Prepper
                → OpenSearch (otel-v1-apm-span-*)
                    → OpenSearch Dashboards Agent Traces UI

Span types (OpenSearch 3.6+ understands these via gen_ai.operation.name):
    "agent"        → green  [Agent] box
    "chat"         → pink   [LLM]   box
    "execute_tool" → brown  [Tool]  box

Environment variables:
    OTEL_EXPORTER_OTLP_ENDPOINT    → OTel Collector URL (default: http://localhost:4318)
    OPENSEARCH_DASHBOARDS_URL      → Dashboards base URL (default: http://localhost:5601)
"""

import os
import logging
from contextlib import contextmanager
from typing import Dict

from opentelemetry import trace, propagate
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.propagate import inject, extract

logger = logging.getLogger("observability.otel")


class OTelSetup:
    def __init__(self, project: str):
        self.project    = project
        self.dashboards = os.getenv("OPENSEARCH_DASHBOARDS_URL", "http://localhost:5601").rstrip("/")
        self.tracer     = self._init_tracer()

    def _init_tracer(self):
        resource = Resource.create({
            "service.name":           self.project,
            "service.version":        "1.0.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "local"),
        })

        endpoint = os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://localhost:4318"
        )

        exporter = OTLPSpanExporter(
            endpoint=f"{endpoint}/v1/traces",
        )

        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        logger.info("OTel exporter → %s/v1/traces", endpoint)
        ws_id = os.getenv("OPENSEARCH_WORKSPACE_ID", "")
        if ws_id:
            logger.info("View traces   → %s/w/%s/app/agentTraces", self.dashboards, ws_id)
        else:
            logger.info("View traces   → %s/app/agentTraces", self.dashboards)
            logger.info("Tip: run scripts/setup_observability.py to get your workspace URL")

        return trace.get_tracer(self.project)

    # ── Root pipeline span ──────────────────────────────────────────────────

    @contextmanager
    def root_span(self, name: str, attributes: dict = None):
        """
        Wraps the entire pipeline run in one root span.
        All agent spans inside become children → full trace tree in OpenSearch.
        """
        with self.tracer.start_as_current_span(
            name,
            kind=SpanKind.SERVER,
            attributes=self._safe_attrs({
                "gen_ai.operation.name": "agent",
                **(attributes or {}),
            }),
        ) as span:
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    # ── Agent span ──────────────────────────────────────────────────────────

    @contextmanager
    def agent_span(self, agent_name: str, stage: str, attributes: dict = None):
        """
        Agent-level span — renders as green [Agent] box in OpenSearch.
        """
        with self.tracer.start_as_current_span(
            agent_name,
            kind=SpanKind.INTERNAL,
            attributes=self._safe_attrs({
                "gen_ai.operation.name": "agent",
                "agent.name":            agent_name,
                "workflow.stage":        stage,
                "service.name":          self.project,
                **(attributes or {}),
            }),
        ) as span:
            yield span

    # ── Sub-spans ───────────────────────────────────────────────────────────

    @contextmanager
    def retrieval_span(self, agent_name: str, query: str = ""):
        """Retrieval step — for RAG or database lookups."""
        with self.tracer.start_as_current_span(
            "retrieval",
            kind=SpanKind.CLIENT,
            attributes=self._safe_attrs({
                "gen_ai.operation.name": "agent",
                "agent.name":            agent_name,
                "retrieval.query":       query,
                "db.system":             "opensearch",
            }),
        ) as span:
            yield span

    @contextmanager
    def tool_span(self, tool_name: str, agent_name: str, attributes: dict = None):
        """
        Tool call span — renders as brown [Tool] box in OpenSearch.
        """
        with self.tracer.start_as_current_span(
            f"tool_call.{tool_name}",
            kind=SpanKind.INTERNAL,
            attributes=self._safe_attrs({
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name":      tool_name,
                "agent.name":            agent_name,
                "tool.name":             tool_name,
                **(attributes or {}),
            }),
        ) as span:
            yield span

    @contextmanager
    def reasoning_span(self, agent_name: str):
        """Reasoning step — for planner/RCA agents."""
        with self.tracer.start_as_current_span(
            "reasoning",
            kind=SpanKind.INTERNAL,
            attributes=self._safe_attrs({
                "gen_ai.operation.name": "agent",
                "agent.name":            agent_name,
            }),
        ) as span:
            yield span

    @contextmanager
    def evaluation_span(self, agent_name: str, eval_score: float = None):
        """Evaluation step — for quality scoring."""
        attrs = {
            "gen_ai.operation.name": "agent",
            "agent.name":            agent_name,
        }
        if eval_score is not None:
            attrs["eval.score"] = eval_score
        with self.tracer.start_as_current_span(
            "evaluation",
            kind=SpanKind.INTERNAL,
            attributes=self._safe_attrs(attrs),
        ) as span:
            yield span

    @contextmanager
    def llm_span(
        self,
        name:       str,
        prompt:     str,
        model:      str,
        agent_name: str,
        eval_score: float = None,
        attributes: dict  = None,
    ):
        """
        LLM generation span — renders as pink [LLM] box in OpenSearch.
        Carries all gen_ai.* semantic attributes.
        """
        attrs = {
            "gen_ai.operation.name":  "chat",
            "gen_ai.system":          os.getenv("LLM_PROVIDER", "groq"),
            "gen_ai.request.model":   model,
            "gen_ai.prompt":          prompt[:2000],
            "agent.name":             agent_name,
            **(attributes or {}),
        }
        if eval_score is not None:
            attrs["eval.score"] = eval_score

        with self.tracer.start_as_current_span(
            name,
            kind=SpanKind.CLIENT,
            attributes=self._safe_attrs(attrs),
        ) as span:
            yield span

    # ── Cross-agent context propagation ────────────────────────────────────

    def inject_context(self) -> Dict[str, str]:
        """
        Returns the current W3C traceparent carrier.
        Store this in your agent state to link spans across agent boundaries.
        """
        carrier = {}
        inject(carrier)
        return carrier

    @contextmanager
    def continued_span(self, name: str, carrier: dict, attributes: dict = None):
        """
        Continues a trace from a W3C carrier.
        Used to attach agent spans to the root pipeline span across
        LangGraph state boundaries.
        """
        ctx = extract(carrier)
        with self.tracer.start_as_current_span(
            name,
            context=ctx,
            kind=SpanKind.INTERNAL,
            attributes=self._safe_attrs(attributes or {}),
        ) as span:
            yield span

    def shutdown(self):
        """
        Flush all pending spans before process exits.
        Always call this at the end of your pipeline run.
        """
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
            logger.info("Tracer provider shut down — all spans flushed.")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _safe_attrs(self, attrs: dict) -> dict:
        """OTel only accepts str, bool, int, float — filters out None."""
        result = {}
        for k, v in attrs.items():
            if v is None:
                continue
            if isinstance(v, (str, bool, int, float)):
                result[k] = v
            else:
                result[k] = str(v)
        return result
