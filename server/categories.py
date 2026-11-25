"""The rating categories. They are fixed in the code, not stored in the database.

A rating is one score from MIN_SCORE to MAX_SCORE in every category; a person's
score for a film is the sum of their category scores (3 to 30).
"""

MIN_SCORE = 1
MAX_SCORE = 10
MAX_COMMENT_LENGTH = 1000

CATEGORIES = [
    {
        "key": "aesthetic",
        "label": "Aesthetic",
        "description": "Well-executed use of archival material",
        "anchors": {"1": "Mash-Up", "5": "Unique and Well Executed", "10": "Unexpected and Surprising"},
    },
    {
        "key": "sound",
        "label": "Sound(track)",
        "description": "Degree of creativity in musical/soundtrack choice, its application and sound editing",
        "anchors": {"1": "Filler/Temp Music", "5": "Appropriate Sounds", "10": "Elevating the Film"},
    },
    {
        "key": "appeal",
        "label": "Appeal",
        "description": "Level of creativity and thoughtfulness",
        "anchors": {"1": "Dull", "5": "Good Effort", "10": "Inspired"},
    },
]

CATEGORY_KEYS = [c["key"] for c in CATEGORIES]
