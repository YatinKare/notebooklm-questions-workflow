from __future__ import annotations

from typing import Any

STRICT_JSON_PREAMBLE = (
    "Respond with ONLY valid JSON. No prose, no markdown, no code fences. "
    "Output must begin with '[' and end with ']'.\n\n"
)

_TYPE_HINTS: dict[str, str] = {
    "TF": "T/F",
    "MCQ": "MCQ",
    "SELECT_MULTIPLE": "Select all that apply",
    "MATCHING": "Matching",
    "SHORT_ANSWER": "Short answer",
    "SHORT_ANSWER_MATH": "Short answer (math)",
    "LONG_ANSWER": "Long answer",
}

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def build_notebooklm_prompt(
    questions: list[dict[str, Any]], *, strict: bool = False
) -> str:
    lines: list[str] = []
    if strict:
        lines.append(STRICT_JSON_PREAMBLE.rstrip())
        lines.append("")
    lines.append("Please answer the following questions using the source material.")
    lines.append("For each, give the answer and a 1-2 sentence justification.")
    lines.append(
        'Format your response as JSON: [{"q": <number>, "answer": <answer>, '
        '"justification": <text>}, ...]'
    )
    lines.append("")
    for q in questions:
        hint = _TYPE_HINTS.get(q["type"], q["type"])
        lines.append(f"{q['number']}. ({hint}) {q['stem']}")
        opts = q.get("options")
        if opts:
            for i, opt in enumerate(opts):
                lines.append(f"   {_LETTERS[i]}) {opt}")
    return "\n".join(lines)
