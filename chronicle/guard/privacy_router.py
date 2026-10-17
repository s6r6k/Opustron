"""Privacy router: PII detection → pseudonymisation → routing decision.

The router sits between every LLM caller and the external API.
Text that contains PII is pseudonymised before it leaves the machine;
the response is re-identified before it reaches the caller.

    router = PrivacyRouter()

    # Before LLM call:
    redacted, mapping = router.redact(original_text)

    # After LLM call:
    clean_response = router.restore(llm_response, mapping)
"""

from __future__ import annotations

from typing import Literal

from .pii_detector import detect
from .pseudonymizer import PseudonymMapping, pseudonymize, reidentify


class PrivacyRouter:

    def redact(
        self,
        text: str,
        mapping: PseudonymMapping | None = None,
    ) -> tuple[str, PseudonymMapping]:
        """Detect PII and pseudonymise.

        Returns (redacted_text, mapping). Pass an existing mapping to share
        tokens across multiple texts in the same request.
        """
        entities = detect(text)
        return pseudonymize(text, mapping, entities=entities)

    def restore(self, text: str, mapping: PseudonymMapping) -> str:
        """Re-identify ENTITY_N tokens in an LLM response."""
        return reidentify(text, mapping)

    def route(self, text: str) -> Literal["local", "external"]:
        """Decide whether text must stay local or can go to an external API.

        Returns "local" if PII is detected (caller should run a local model),
        "external" if the text is clean and safe to send to Token Factory.
        After calling redact(), the returned text is always safe to route
        "external" — this method is for pre-redaction checks only.
        """
        return "local" if detect(text) else "external"

    def redact_messages(
        self,
        messages: list[dict[str, str]],
        mapping: PseudonymMapping | None = None,
    ) -> tuple[list[dict[str, str]], PseudonymMapping]:
        """Redact PII from every message in a chat-completion messages list.

        Returns (redacted_messages, mapping) where mapping is shared across
        all messages so the same person gets the same token.
        """
        if mapping is None:
            mapping = PseudonymMapping()

        redacted: list[dict[str, str]] = []
        for msg in messages:
            content = msg.get("content", "")
            redacted_content, mapping = self.redact(content, mapping)
            redacted.append({**msg, "content": redacted_content})

        return redacted, mapping
