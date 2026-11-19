from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    id: int
    email: str
    created_at: str
    is_admin: bool = False
    is_judge: bool = False

    @property
    def roles(self) -> list[str]:
        return [r for r, on in (("admin", self.is_admin), ("judge", self.is_judge)) if on]
