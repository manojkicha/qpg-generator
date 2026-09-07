"""Observability utilities — Langfuse tracing and MLflow tracking.

Based on SDD Section 8.3:
- Langfuse traces every agent step (prompt, retrieved context, output, latency, token cost)
- MLflow tracks prompt/template versions and offline evaluation runs
- Application Insights (or equivalent) covers standard API health
"""

import logging
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Any, AsyncGenerator, Callable, Generator, Optional

from langfuse import Langfuse

from app.core.config import settings

logger = logging.getLogger(__name__)


_langfuse_client: Optional[Langfuse] = None


def get_langfuse_client() -> Langfuse:
    """Get or create Langfuse client."""
    global _langfuse_client
    if _langfuse_client is None:
        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse_client


@contextmanager
def trace_agent(
    agent_name: str,
    inputs: dict,
    metadata: Optional[dict] = None,
) -> Generator[Any, None, None]:
    """Context manager to trace an agent step with Langfuse."""
    try:
        client = get_langfuse_client()
        trace = client.trace(
            name=agent_name,
            metadata=metadata or {},
            input=inputs,
        )
        yield trace
    except Exception as e:
        logger.warning("Langfuse trace failed: %s", e)
        yield None


@asynccontextmanager
async def trace_agent_async(
    agent_name: str,
    inputs: dict,
    metadata: Optional[dict] = None,
) -> AsyncGenerator[Any, None]:
    """Async context manager for agent tracing."""
    try:
        client = get_langfuse_client()
        trace = client.trace(
            name=agent_name,
            metadata=metadata or {},
            input=inputs,
        )
        yield trace
    except Exception as e:
        logger.warning("Langfuse trace failed: %s", e)
        yield None


def traced_agent(agent_name: str) -> Callable:
    """Decorator to trace agent execution."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            with trace_agent(agent_name, {"args": str(args), "kwargs": str(kwargs)}):
                result = await func(*args, **kwargs)
                return result

        return wrapper

    return decorator


def log_quality_metrics(
    flagged_count: int,
    total_count: int,
    retry_count: int,
) -> None:
    """Log generation quality metrics.

    Based on SDD Section 8.3: lightweight quality dashboard surfaces
    the Validator Agent's flag rate as a leading indicator.
    """
    if total_count == 0:
        return

    flag_rate = (flagged_count / total_count) * 100
    retry_rate = (retry_count / total_count) * 100

    logger.info(
        "Generation quality metrics: total=%d, flagged=%d (%.1f%%), retries=%d (%.1f%%)",
        total_count, flagged_count, flag_rate, retry_count, retry_rate,
    )

    try:
        import mlflow

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        with mlflow.start_run(nested=True):
            mlflow.log_metric("flag_rate", flag_rate)
            mlflow.log_metric("retry_rate", retry_rate)
            mlflow.log_metric("total_questions", total_count)
    except Exception as e:
        logger.debug("MLflow logging skipped: %s", e)