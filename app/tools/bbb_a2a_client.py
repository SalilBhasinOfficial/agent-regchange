"""A2A bridge to an external regulatory-corpus MCP gateway.

Curator stays IP-clean: this module *consumes* a remote MCP/A2A surface
rather than embedding any of its data layer. When ``BBB_MCP_BEARER`` is
unset (the default for the hackathon public repo), every call is a
silent no-op returning ``[]`` so the offline path stays green.

Wire-up: ``app.sub_agents.qna.real_qna`` enriches its prompt with the
snippets this returns. ``app.sub_agents.reflector.reflect_and_requery``
may optionally fall back to this when the Spanner Graph backend returns
empty extra context.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "https://mcp.aidni.cloud/mcp"
_DEFAULT_TOOL_NAME = "regulatory_deep_lookup"
_DEFAULT_TIMEOUT_S = 8.0


def _endpoint() -> str:
    return os.environ.get("BBB_MCP_ENDPOINT", _DEFAULT_ENDPOINT)


def _bearer() -> str | None:
    token = os.environ.get("BBB_MCP_BEARER")
    return token.strip() if token else None


def is_enabled() -> bool:
    """True when the bearer env var is set; False otherwise (offline-safe)."""
    return _bearer() is not None


def regulatory_deep_lookup(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Query the remote MCP gateway for regulatory snippets.

    Args:
        query: free-text question or topic.
        k: max number of snippets requested.

    Returns:
        List of dicts, each shaped roughly as
        ``{"title": str, "source_url": str, "snippet": str,
        "citation_count": int}``. Empty list when the bridge is disabled
        (no bearer), the endpoint errors, or the response is malformed.
    """
    if not is_enabled():
        return []

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": os.environ.get("BBB_MCP_TOOL_NAME", _DEFAULT_TOOL_NAME),
            "arguments": {"query": query, "k": k},
        },
    }
    headers = {
        "Authorization": f"Bearer {_bearer()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = httpx.post(
            _endpoint(),
            json=payload,
            headers=headers,
            timeout=_DEFAULT_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 — fail-quiet by design
        logger.warning("bbb_a2a_client: lookup failed (%s); returning empty.", exc)
        return []

    return _coerce_result(body, k)


def _coerce_result(body: dict[str, Any], k: int) -> list[dict[str, Any]]:
    """Best-effort flatten of an MCP JSON-RPC reply into a list of dicts.

    Handles two response shapes the gateway is likely to return:

      * ``{"result": {"content": [{"type": "json", "json": [...]}]}}``
      * ``{"result": [...]}`` (legacy / direct)
    """
    result = body.get("result")
    if isinstance(result, list):
        return result[:k]

    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    inner = item.get("json") or item.get("data")
                    if isinstance(inner, list):
                        return inner[:k]
        data = result.get("data")
        if isinstance(data, list):
            return data[:k]

    return []
