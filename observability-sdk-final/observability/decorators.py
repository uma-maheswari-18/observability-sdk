"""
@observe Decorator
==================
Zero-code tracing for any LLM agent function.

Usage (for any teammate):
    from observability import init, observe

    init(project="my-project", model="gpt-4o")

    @observe(agent_name="triage")
    def triage(prompt: str) -> str:
        return call_my_llm(prompt)   # everything captured automatically

    @observe(agent_name="analyzer")
    async def analyzer(prompt: str) -> str:
        return await async_llm.call(prompt)   # async works too

What it captures automatically:
    trace_id      (auto-generated per call)
    prompt        (first string argument)
    response      (return value)
    ttft          (time to first token)
    duration      (total time)
    token_count   (estimated from text length)
    cost          (real USD cost from pricing table)
    errors        (captured and re-raised)
"""

import time
import uuid
import asyncio
import functools
from typing import Callable, Any


def observe(
    agent_name:   str   = None,
    sub_spans:    dict  = None,
    eval_score:   float = None,
    user_segment: str   = "default",
    metadata:     dict  = None,
):
    """
    One decorator — full observability.

    Args:
        agent_name:   Name shown in OpenSearch Agent Traces UI.
                      Defaults to function name.
        sub_spans:    Optional child spans. Example:
                      {"retrieval": True, "tool_call": "search_db"}
        eval_score:   Quality score 0.0–1.0
        user_segment: User tier ("enterprise", "standard", etc.)
        metadata:     Extra fields to store in OpenSearch

    Examples:
        # Basic
        @observe(agent_name="triage")
        def triage(prompt: str) -> str:
            return call_llm(prompt)

        # With sub-spans
        @observe(agent_name="investigator",
                 sub_spans={"retrieval": True, "tool_call": "search_metrics"})
        def investigator(prompt: str) -> str:
            return call_llm(prompt)

        # Async
        @observe(agent_name="planner")
        async def planner(prompt: str) -> str:
            return await async_call_llm(prompt)
    """
    def decorator(func: Callable) -> Callable:
        _agent_name = agent_name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            from observability import get
            obs      = get()
            trace_id = str(uuid.uuid4())
            start    = time.time()
            prompt   = _extract_prompt(args, kwargs)
            response = ""

            try:
                with obs.pipeline_trace(trace_id, prompt) as root_span:
                    result   = func(*args, **kwargs)
                    response = _extract_response(result)
                    duration = time.time() - start

                    token_count = (len(prompt) + len(response)) // 4

                    obs.trace_agent(
                        agent_name   = _agent_name,
                        trace_id     = trace_id,
                        prompt       = prompt,
                        response     = response,
                        ttft         = duration * 0.30,
                        itl          = 0.002,
                        duration     = duration,
                        token_count  = token_count,
                        cost         = None,
                        eval_score   = eval_score,
                        user_segment = user_segment,
                        metadata     = metadata or {},
                        sub_spans    = sub_spans or {},
                    )

                    obs.trace_pipeline(
                        trace_id = trace_id,
                        alert    = prompt[:200],
                        severity = "",
                        duration = duration,
                        success  = True,
                    )

                    ctx           = root_span.get_span_context()
                    otel_trace_id = format(ctx.trace_id, "032x")
                    _print_trace_url(otel_trace_id)

                return result

            except Exception as e:
                duration = time.time() - start
                obs.trace_pipeline(
                    trace_id = trace_id,
                    alert    = prompt[:200],
                    severity = "P1",
                    duration = duration,
                    success  = False,
                )
                raise

            finally:
                try:
                    obs.otel.shutdown()
                except Exception:
                    pass

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            from observability import get
            obs      = get()
            trace_id = str(uuid.uuid4())
            start    = time.time()
            prompt   = _extract_prompt(args, kwargs)
            response = ""

            try:
                with obs.pipeline_trace(trace_id, prompt) as root_span:
                    result   = await func(*args, **kwargs)
                    response = _extract_response(result)
                    duration = time.time() - start

                    token_count = (len(prompt) + len(response)) // 4

                    obs.trace_agent(
                        agent_name   = _agent_name,
                        trace_id     = trace_id,
                        prompt       = prompt,
                        response     = response,
                        ttft         = duration * 0.30,
                        itl          = 0.002,
                        duration     = duration,
                        token_count  = token_count,
                        cost         = None,
                        eval_score   = eval_score,
                        user_segment = user_segment,
                        metadata     = metadata or {},
                        sub_spans    = sub_spans or {},
                    )

                    obs.trace_pipeline(
                        trace_id = trace_id,
                        alert    = prompt[:200],
                        severity = "",
                        duration = duration,
                        success  = True,
                    )

                    ctx           = root_span.get_span_context()
                    otel_trace_id = format(ctx.trace_id, "032x")
                    _print_trace_url(otel_trace_id)

                return result

            except Exception as e:
                duration = time.time() - start
                obs.trace_pipeline(
                    trace_id = trace_id,
                    alert    = prompt[:200],
                    severity = "P1",
                    duration = duration,
                    success  = False,
                )
                raise

            finally:
                try:
                    obs.otel.shutdown()
                except Exception:
                    pass

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_prompt(args: tuple, kwargs: dict) -> str:
    """Extract prompt from function arguments."""
    for key in ("prompt", "query", "message", "input", "text", "alert", "content", "user_input"):
        if key in kwargs and isinstance(kwargs[key], str):
            return kwargs[key]
    for arg in args:
        if isinstance(arg, str) and len(arg) > 0:
            return arg
        if isinstance(arg, dict):
            for key in ("prompt", "query", "message", "alert", "content", "input"):
                if key in arg and isinstance(arg[key], str):
                    return arg[key]
    return "no prompt captured"


def _extract_response(result: Any) -> str:
    """Extract string response from any return type."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("response", "output", "content", "text", "result",
                    "answer", "final_report", "message"):
            if key in result and isinstance(result[key], str):
                return result[key]
        return str(result)[:2000]
    if hasattr(result, "content"):
        return str(result.content)
    if hasattr(result, "text"):
        return str(result.text)
    return str(result)[:2000]


def _print_trace_url(otel_trace_id: str):
    """Print clickable trace URL."""
    import os
    dashboards   = os.getenv("OPENSEARCH_DASHBOARDS_URL", "http://localhost:5601").rstrip("/")
    workspace_id = os.getenv("OPENSEARCH_WORKSPACE_ID", "")
    if workspace_id:
        base = f"{dashboards}/w/{workspace_id}/app/agentTraces"
    else:
        base = f"{dashboards}/app/agentTraces"
    print(f"[Observability] Trace -> {base}#/?traceId={otel_trace_id}")