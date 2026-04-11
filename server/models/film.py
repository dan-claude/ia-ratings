from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Film:
    id: int
    identifier: str
    title: Optional[str]
