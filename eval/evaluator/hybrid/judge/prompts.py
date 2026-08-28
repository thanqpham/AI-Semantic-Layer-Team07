"""Versioned rubric and judge prompt builders (spec §8.3)."""

from __future__ import annotations

RUBRIC_VERSION = "1.0.0"

RUBRIC: tuple[tuple[str, float], ...] = (
    ("business_meaning", 0.40),
    ("reference_alignment", 0.25),
    ("unsupported_assumptions", 0.20),
    ("clarity", 0.15),
)

PROMPT_VERSIONS = {
    "business_semantic_correctness": "business-semantics-v2",
    "business_definition_correctness": "business-definition-v3",
    "formula_semantic_correctness": "formula-semantics-v3",
}


def judge_system_prompt() -> str:
    """Instruct JSON-only, rubric-structured judging without chain-of-thought."""
    criteria = ", ".join(name for name, _ in RUBRIC)
    return (
        "You are a strict data-semantic quality judge for a Vietnamese enterprise semantic layer. "
        f"Score each criterion ({criteria}) from 0.0 to 1.0. "
        "Respond with ONLY a JSON object: "
        '{"criteria": [{"name": "<criterion>", "score": <0.0-1.0>, "justification": "<max 15 words>"}], '
        '"overall": <0.0-1.0>, "summary": "<max 20 words>"}. '
        "Judge business meaning in Vietnamese business language. "
        "Keep each justification under 15 words and the summary under 20 words; "
        "never include step-by-step reasoning. "
        "Your entire response must be that JSON object — nothing before or after it."
    )


def judge_user_prompt(
    title: str,
    request: str,
    schema_context: str,
    reference: str,
    response: str,
) -> str:
    """Render one blinded judge payload with rubric-ordered sections."""
    return (
        f"## Task: {title}\n\n"
        f"## Request\n{request}\n\n"
        f"## Schema context\n{schema_context}\n\n"
        f"## Reviewed reference\n{reference}\n\n"
        f"## Candidate response\n{response}\n\n"
        "Judge the candidate response against the reviewed reference."
    )
