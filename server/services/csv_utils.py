"""Helpers for writing CSV that people open in spreadsheet apps."""


def csv_safe(value):
    """Stop spreadsheet apps treating text as a formula (CSV injection).

    Excel/Sheets/LibreOffice evaluate a cell that starts with = + - @ (or a tab /
    carriage return). Text from outside the app (film titles from archive.org,
    judges' notes, usernames) must never run as a formula, so such cells get a
    leading apostrophe. Non-strings (numbers, None) pass through unchanged.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
