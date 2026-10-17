"""Tests for chronicle/ingest/llm.py (backwards-compat shim)."""

from chronicle.guard.llm_client import LLMClient
from chronicle.ingest.llm import OpenAICompatLLM


def test_openai_compat_llm_is_guard_client():
    """The shim must re-export LLMClient so existing call sites keep working."""
    assert OpenAICompatLLM is LLMClient
