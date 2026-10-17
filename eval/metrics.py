"""Small standalone accuracy summary for development fixtures only."""
from collections import defaultdict

def summarize(rows: list[dict]) -> dict:
    groups = defaultdict(lambda: [0, 0])
    for row in rows:
        kind = row.get("category", "unknown")
        groups[kind][1] += 1
        groups[kind][0] += int(bool(row["correct"]))
    return {kind: {"correct": c, "total": n, "accuracy": c / n if n else 0.0} for kind, (c, n) in sorted(groups.items())}
