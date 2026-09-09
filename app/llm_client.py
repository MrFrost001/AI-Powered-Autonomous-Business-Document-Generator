"""
Thin wrapper around Groq's free-tier LLM API - now built on the LangChain
framework (langchain-core + langchain-groq) instead of the raw `groq` SDK.

Real engineering improvement implemented here: RETRY & FALLBACK LOGIC.

Free-tier LLM endpoints (Groq, Gemini, etc.) are rate-limited and occasionally
flaky. An agent that crashes or returns a 500 whenever the model provider
hiccups is not production-grade. So every call to the LLM in this project:

  1. Retries with exponential backoff (handles transient network / 429 errors).
  2. Times out instead of hanging forever.
  3. Falls back to a deterministic, template-based generator if the LLM is
     unavailable (no API key configured, all retries exhausted, malformed
     response, etc.) so the agent ALWAYS returns a usable document instead
     of failing the request.

This makes the whole pipeline runnable and demoable with zero API key/cost
(fallback mode), while still using a real hosted model when GROQ_API_KEY is
present.

Why LangChain: `ChatGroq` (langchain_groq) gives a standard `BaseChatModel`
interface (`SystemMessage` / `HumanMessage` in, an `AIMessage` out) instead of
hand-rolling the Groq HTTP payload. That keeps this module - and only this
module - responsible for talking to the model; planner.py and executor.py
still just call `call_llm` / `call_llm_json` and never know (or care) which
framework is behind them.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("agent.llm")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
BASE_BACKOFF_SECONDS = float(os.getenv("LLM_BASE_BACKOFF", "1.5"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT", "20"))

logger.info("LLM configuration loaded")
logger.info("GROQ_API_KEY configured: %s", bool(GROQ_API_KEY))
logger.info("GROQ_MODEL: %s", GROQ_MODEL)
logger.info("LLM backend: LangChain (langchain_groq.ChatGroq)")


class LLMUnavailableError(Exception):
    """Raised when the LLM cannot be reached after all retries."""


def _build_chat_model(json_mode: bool) -> ChatGroq:
    """
    Build a LangChain `ChatGroq` chat model.

    Created fresh per call - this is cheap (no network I/O happens until
    `.invoke()` is called), so the app still boots without the package
    configured or a key set, exactly like the old lazily-imported `Groq`
    client did.
    """
    kwargs: Dict[str, Any] = {
        "api_key": GROQ_API_KEY,
        "model": GROQ_MODEL,
        "temperature": 0.4,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "max_retries": 0,  # we do our own retry/backoff loop below
    }
    if json_mode:
        # Groq's OpenAI-compatible JSON mode, passed through LangChain.
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatGroq(**kwargs)


def llm_configured() -> bool:
    return bool(GROQ_API_KEY)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
) -> Optional[str]:
    """
    Call Groq (via LangChain's `ChatGroq` chat model) with retry + exponential
    backoff.

    Retries transient failures such as:
      - timeouts
      - connection errors
      - rate limits

    Does not retry permanent configuration errors such as:
      - invalid API key
      - unavailable model
      - permission errors

    Returns None when fallback generation should be used.
    """

    if not llm_configured():
        logger.info(
            "GROQ_API_KEY not set - skipping LLM call; "
            "caller will use fallback."
        )
        return None

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    last_error: Optional[Exception] = None
    attempt = 0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Calling Groq model '%s' via LangChain (attempt %s/%s)",
                GROQ_MODEL,
                attempt,
                MAX_RETRIES,
            )

            chat_model = _build_chat_model(json_mode=json_mode)
            ai_message = chat_model.invoke(messages)
            content = getattr(ai_message, "content", None)

            if not content or not str(content).strip():
                raise ValueError("Empty response from LLM")

            logger.info(
                "Groq call successful using model '%s'",
                GROQ_MODEL,
            )

            return str(content).strip()

        except Exception as exc:
            last_error = exc
            error_text = str(exc).lower()

            # Permanent errors — don't waste retries
            permanent_error = any(
                keyword in error_text
                for keyword in [
                    "model_not_found",
                    "does not exist",
                    "invalid api key",
                    "authentication",
                    "unauthorized",
                    "permission",
                    "forbidden",
                ]
            )

            if permanent_error:
                logger.error(
                    "Permanent Groq error; skipping retries: %s",
                    exc,
                )
                break

            # Temporary error — retry
            wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))

            logger.warning(
                "LLM call failed (attempt %s/%s): %s. "
                "Backing off %.1fs.",
                attempt,
                MAX_RETRIES,
                exc,
                wait,
            )

            if attempt < MAX_RETRIES:
                time.sleep(wait)

    logger.error(
        "LLM unavailable after %s attempts: %s. "
        "Falling back to templates.",
        attempt,
        last_error,
    )

    return None


def call_llm_json(system_prompt: str, user_prompt: str) -> Optional[dict]:
    """Same as call_llm but parses JSON; returns None on any failure so the
    caller can fall back cleanly instead of crashing on a JSONDecodeError."""
    raw = call_llm(system_prompt, user_prompt, json_mode=True)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned invalid JSON, falling back: %s", exc)
        return None
