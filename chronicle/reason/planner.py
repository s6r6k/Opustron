"""Rule-based starter planner. Replace/augment with structured Nemotron planning."""
import re
from datetime import date
from .models import QueryPlan

ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")

def plan_query(question: str) -> QueryPlan:
    match = ISO_DATE.search(question)
    ref = date.fromisoformat(match.group(1)) if match else None
    lower = question.lower()
    if ref:
        kind = "as_of"
    elif any(word in lower for word in ("before", "after", "earlier than", "later than")):
        kind = "ordering_or_history"
    elif any(word in lower for word in ("currently", "now", "latest", "current")):
        kind = "current"
    else:
        kind = "search"
    return QueryPlan(question=question, kind=kind, reference_date=ref)
