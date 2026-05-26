"""
Observability SDK
=================
One-line LLM observability for any AI agent.
Sends traces to OpenSearch — visible in Agent Traces UI.

Usage:
    from observability import init, get

    init(project="my-agent", model="llama-3.1-8b-instant")

    obs = get()
    with obs.pipeline_trace(trace_id, alert):
        ...
"""

import logging
from .core import ObservabilityFramework

_framework: ObservabilityFramework | None = None


def init(project: str = "default", model: str = "groq") -> ObservabilityFramework:
    """
    Initialize the observability SDK.
    Call once at the top of your project.

    Args:
        project: Your project name — used as index prefix in OpenSearch.
        model:   LLM model name (e.g. llama-3.1-8b-instant, gpt-4o-mini).
                 Used for real cost calculation.
    """
    global _framework
    _framework = ObservabilityFramework(project=project, model=model)
    _framework.start()
    return _framework


def get() -> ObservabilityFramework:
    """Get the global observability instance. Call init() first."""
    if _framework is None:
        raise RuntimeError(
            "Observability SDK not initialized. Call init() first.\n"
            "Example: from observability import init; init(project='my-agent')"
        )
    return _framework


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure observability SDK internal logging.

    Example:
        import logging
        from observability import configure_logging
        configure_logging(level=logging.DEBUG)
    """
    sdk_logger = logging.getLogger("observability")
    if not sdk_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
        sdk_logger.addHandler(handler)
    sdk_logger.setLevel(level)


__all__ = ["init", "get", "configure_logging", "ObservabilityFramework"]
