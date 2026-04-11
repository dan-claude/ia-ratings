# RECREATE guardrails

This file documents the operational practices that keep code and documentation
correct and trustworthy over time. These rules apply to every change request.

---

## CODE EDITING RULES

### Rule 1 — Read before editing
Before making any `str_replace` or file edit, read the relevant section of
the file to confirm the exact current content. Never edit from memory.

### Rule 2 — Verify after every edit (MANDATORY)
After every `str_replace` or file edit, immediately read back the affected
lines and explicitly confirm:
1. The intended new content is present and correct.
2. Nothing that was supposed to be preserved was accidentally deleted.

Do this before moving on to the next edit or running any build.

This rule exists because `str_replace` is a pure substitution — whatever is
in `old_str` is permanently deleted. An additive change that puts new content
in `new_str` but forgets to re-include the original `old_str` content will
silently delete it. The verify step catches this immediately.

### Rule 3 — One logical change per edit
Make the smallest edit that achieves the goal. If a change touches multiple
unrelated things, split it into separate edits so each can be verified
independently.

---

## DOCUMENTATION RULES

### Rule 4 — RECREATE diff acknowledgment
For any change request, explicitly state which sections of
`RECREATE_WITH_CLAUDE.txt` were modified, or explicitly state
"No RECREATE sections were modified."

Suggested wording:
- "RECREATE updated in sections: <list sections>."
- "No RECREATE sections were modified."

### Rule 5 — Do not delete or shorten RECREATE
When editing `RECREATE_WITH_CLAUDE.txt`, only append or edit targeted
sections. Do not delete or shorten existing sections unless explicitly
asked to remove them.

Before any non-trivial RECREATE edit, note the current section list as a
reference in case a later edit accidentally truncates content.

### Rule 6 — RECREATE checksum (belt-and-suspenders)
The build tool (`tools/build_zip.py`) validates a normalized SHA256 of the
release ZIP. This acts as a checksum for the full project state including
RECREATE. Always run the build tool after changes to confirm integrity.
