"""Privacy and egress controls for Chronicle.

Quick start:
    from chronicle.guard import llm, router

    # Use the LLM (automatically redacts PII, logs egress):
    response = llm.complete(messages=[{"role": "user", "content": "..."}])

    # Manual redact / restore:
    redacted, mapping = router.redact("Alice Tan's email is alice@example.com")
    # → "PERSON_1's email is EMAIL_1"
    original = router.restore(llm_response, mapping)
"""

from .egress_logger import EgressLogger, get_logger
from .llm_client import LLMClient, llm
from .pii_detector import PiiMatch, contains_pii, detect
from .privacy_router import PrivacyRouter
from .pseudonymizer import PseudonymMapping, pseudonymize, reidentify

router = PrivacyRouter()

__all__ = [
    "llm",
    "router",
    "LLMClient",
    "PrivacyRouter",
    "PseudonymMapping",
    "PiiMatch",
    "EgressLogger",
    "get_logger",
    "detect",
    "contains_pii",
    "pseudonymize",
    "reidentify",
]
