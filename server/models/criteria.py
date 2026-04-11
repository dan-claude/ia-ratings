from dataclasses import dataclass

@dataclass(frozen=True)
class Criterion:
    id: int
    key: str
    label: str
    min_score: int
    max_score: int
    sort_order: int
    active: int
