from .models import Evidence

def should_abstain(evidence: list[Evidence]) -> bool:
    return not evidence
