"""
OpenSearch Client
=================
Handles indexing raw LLM trace documents to OpenSearch.

Two indices per project:
    {project}-traces    → one doc per agent call (prompt, response, TTFT, ITL)
    {project}-pipeline  → one doc per full pipeline run (alert, severity, duration)

Environment variables:
    OPENSEARCH_URL          → e.g. https://localhost:9200 or http://localhost:9200
    OPENSEARCH_USER         → default: admin
    OPENSEARCH_PASS         → your OpenSearch password
    OPENSEARCH_VERIFY_CERTS → true/false (set false for local dev)
"""

import os
import logging
import time
from datetime import datetime, timezone
from opensearchpy import OpenSearch, RequestsHttpConnection

logger = logging.getLogger("observability.opensearch")

_MAX_RETRIES   = 3
_RETRY_BACKOFF = 0.5   # seconds — doubles on each retry (0.5 → 1.0 → 2.0)


class OpenSearchClient:
    def __init__(self, project: str):
        self.project        = project
        self.traces_index   = f"{project}-traces"
        self.pipeline_index = f"{project}-pipeline"
        self.client         = self._connect()
        if self.client:
            self._ensure_indices()

    def _connect(self) -> OpenSearch | None:
        url      = os.getenv("OPENSEARCH_URL",  "http://localhost:9200")
        user     = os.getenv("OPENSEARCH_USER", "admin")
        password = os.getenv("OPENSEARCH_PASS") or os.getenv("OPENSEARCH_PASSWORD", "admin")
        verify   = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"

        use_ssl = url.startswith("https")
        host    = url.replace("https://", "").replace("http://", "")
        parts   = host.split(":")
        h, port = parts[0], int(parts[1]) if len(parts) > 1 else (443 if use_ssl else 9200)

        try:
            client = OpenSearch(
                hosts=[{"host": h, "port": port}],
                http_auth=(user, password),
                use_ssl=use_ssl,
                verify_certs=verify,
                ssl_show_warn=False,
                connection_class=RequestsHttpConnection,
            )
            info = client.info()
            logger.info("Connected — OpenSearch version %s", info["version"]["number"])
            return client
        except Exception as e:
            logger.error(
                "Could not connect to OpenSearch at %s: %s\n"
                "Check OPENSEARCH_URL, OPENSEARCH_USER, OPENSEARCH_PASS in your .env",
                url, e
            )
            return None

    def _ensure_indices(self):
        """Create indices with proper mappings if they don't exist."""
        traces_mapping = {
            "mappings": {
                "properties": {
                    "project":          {"type": "keyword"},
                    "model":            {"type": "keyword"},
                    "agent_name":       {"type": "keyword"},
                    "service_name":     {"type": "keyword"},
                    "trace_id":         {"type": "keyword"},
                    "prompt":           {"type": "text"},
                    "response":         {"type": "text"},
                    "ttft_seconds":     {"type": "float"},
                    "itl_ms":           {"type": "float"},
                    "duration_seconds": {"type": "float"},
                    "token_count":      {"type": "integer"},
                    "input_tokens":     {"type": "integer"},
                    "output_tokens":    {"type": "integer"},
                    "cost_usd":         {"type": "float"},
                    "eval_score":       {"type": "float"},
                    "cache_hit":        {"type": "boolean"},
                    "is_escalated":     {"type": "boolean"},
                    "user_segment":     {"type": "keyword"},
                    "@timestamp":       {"type": "date"},
                    "metadata":         {"type": "object", "dynamic": True},
                }
            }
        }
        pipeline_mapping = {
            "mappings": {
                "properties": {
                    "project":          {"type": "keyword"},
                    "trace_id":         {"type": "keyword"},
                    "alert":            {"type": "text"},
                    "severity":         {"type": "keyword"},
                    "duration_seconds": {"type": "float"},
                    "success":          {"type": "boolean"},
                    "@timestamp":       {"type": "date"},
                }
            }
        }

        for index, mapping in [
            (self.traces_index,   traces_mapping),
            (self.pipeline_index, pipeline_mapping),
        ]:
            try:
                if not self.client.indices.exists(index=index):
                    self.client.indices.create(index=index, body=mapping)
                    logger.info("Created index: %s", index)
                else:
                    logger.debug("Index exists: %s", index)
            except Exception as e:
                logger.error("Index setup failed for %s: %s", index, e)

    def _index_with_retry(self, index: str, doc: dict):
        """Index a document with exponential backoff retry on failure."""
        if not self.client:
            return

        last_error = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self.client.index(index=index, body=doc)
                return                          # success — done
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF * (2 ** (attempt - 1))   # 0.5 → 1.0 → 2.0
                    logger.warning(
                        "Index attempt %d/%d failed for '%s': %s — retrying in %.1fs",
                        attempt, _MAX_RETRIES, index, e, wait
                    )
                    time.sleep(wait)

        # All retries exhausted — log error but never crash the agent
        logger.error(
            "Failed to index doc to '%s' after %d attempts: %s",
            index, _MAX_RETRIES, last_error
        )

    def index_trace(self, doc: dict):
        """Store one agent trace document."""
        doc["@timestamp"] = datetime.now(timezone.utc).isoformat()
        self._index_with_retry(self.traces_index, doc)

    def index_pipeline(self, doc: dict):
        """Store one pipeline run document."""
        doc["@timestamp"] = datetime.now(timezone.utc).isoformat()
        self._index_with_retry(self.pipeline_index, doc)
