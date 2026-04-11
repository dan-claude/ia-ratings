from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    id: int
    email: str
    created_at: str
    is_admin: bool = False
