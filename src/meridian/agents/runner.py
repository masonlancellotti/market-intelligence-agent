"""Agent runner.

One entry point for every LLM call: forces structured tool-use output against a JSON
schema (or returns text), applies prompt caching to system blocks, enforces the hard
daily budget *before* spending, and logs tokens+cost to ``agent_runs`` after. Callers
catch :class:`LLMUnavailable` / :class:`BudgetExceeded` and degrade (heuristics / template
briefs) rather than crash — "degrade, don't overrun".
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from ..config import Settings, get_settings
from ..ops.costs import can_spend, estimate_cost
from ..util import from_json, utcnow_iso


class LLMUnavailable(RuntimeError):
    """No API key configured — agents must degrade."""


class BudgetExceeded(RuntimeError):
    """Daily LLM budget hit — agents must degrade."""


def llm_available(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return s.secrets.has("anthropic_api_key")


_client = None


def _get_client(settings: Settings):
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.secrets.anthropic_api_key)
    return _client


def _log_run(
    agent: str,
    model: str,
    started: str,
    ms: int,
    usage,
    cost: float,
    status: str,
    task_ref: str | None,
    error: str | None,
) -> None:
    from ..db import get_db

    ti = getattr(usage, "input_tokens", 0) if usage else 0
    to = getattr(usage, "output_tokens", 0) if usage else 0
    get_db().execute(
        "INSERT INTO agent_runs"
        "(agent,model,started_at,ms,input_tokens,output_tokens,cost_usd,status,task_ref,error) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (agent, model, started, ms, ti, to, cost, status, task_ref, error),
    )


def _system_blocks(system: str, cache: bool):
    block: dict[str, Any] = {"type": "text", "text": system}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _call(
    *,
    agent: str,
    model: str,
    system: str,
    user: str,
    tools=None,
    tool_choice=None,
    max_tokens: int,
    temperature: float,
    cache: bool,
    task_ref: str | None,
    settings: Settings,
):
    if not llm_available(settings):
        raise LLMUnavailable(f"{agent}: ANTHROPIC_API_KEY not set")

    est = estimate_cost(model, len(system + user) // 3, max_tokens)
    if not can_spend(model, est, settings):
        raise BudgetExceeded(f"{agent}: daily LLM budget would be exceeded (est ${est:.3f})")

    client = _get_client(settings)
    started = utcnow_iso()
    t0 = time.time()
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": _system_blocks(system, cache),
        "messages": [{"role": "user", "content": user}],
    }
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        _log_run(
            agent,
            model,
            started,
            int((time.time() - t0) * 1000),
            None,
            0.0,
            "error",
            task_ref,
            str(e)[:300],
        )
        raise
    ms = int((time.time() - t0) * 1000)
    cost = estimate_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
    _log_run(agent, model, started, ms, resp.usage, cost, "ok", task_ref, None)
    logger.info("agent {} [{}] {}ms ${:.4f}", agent, model, ms, cost)
    return resp, cost


def run_structured(
    agent: str,
    system: str,
    user: str,
    schema: dict,
    *,
    model: str | None = None,
    max_tokens: int = 1500,
    temperature: float = 0.2,
    cache: bool = True,
    task_ref: str | None = None,
    settings: Settings | None = None,
) -> tuple[dict, float]:
    """Force the model to emit JSON matching ``schema`` via tool-use. Returns (obj, cost)."""
    s = settings or get_settings()
    model = model or s.config.models.triage
    tools = [{"name": "emit", "description": "Emit the structured result.", "input_schema": schema}]
    resp, cost = _call(
        agent=agent,
        model=model,
        system=system,
        user=user,
        tools=tools,
        tool_choice={"type": "tool", "name": "emit"},
        max_tokens=max_tokens,
        temperature=temperature,
        cache=cache,
        task_ref=task_ref,
        settings=s,
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input, cost
    # fallback: try to parse text as JSON
    text = "".join(getattr(b, "text", "") for b in resp.content)
    return from_json(text, {}), cost


def run_text(
    agent: str,
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 1500,
    temperature: float = 0.3,
    cache: bool = True,
    task_ref: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, float]:
    s = settings or get_settings()
    model = model or s.config.models.composer
    resp, cost = _call(
        agent=agent,
        model=model,
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=temperature,
        cache=cache,
        task_ref=task_ref,
        settings=s,
    )
    return "".join(getattr(b, "text", "") for b in resp.content), cost


def log_degraded(agent: str, task_ref: str | None = None) -> None:
    """Record a degraded (no-LLM / budget) run so /system reflects it honestly."""
    _log_run(agent, "heuristic", utcnow_iso(), 0, None, 0.0, "degraded", task_ref, None)
