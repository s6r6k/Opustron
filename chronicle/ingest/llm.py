"""Backwards-compatibility shim: chronicle.guard.LLMClient is now the standard LLM client.

``OpenAICompatLLM`` re-exports ``LLMClient`` under the old name so any code that still
imports it keeps working.  No direct openai dependency here — guard owns that.
"""

from chronicle.guard.llm_client import LLMClient as OpenAICompatLLM

__all__ = ["OpenAICompatLLM"]
