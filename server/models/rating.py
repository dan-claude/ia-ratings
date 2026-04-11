from dataclasses import dataclass

@dataclass(frozen=True)
class Rating:
    id: int
    user_id: int
    film_id: int
    created_at: str
    updated_at: str
