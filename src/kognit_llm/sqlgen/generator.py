"""SQL generator: one parameterized statement per intent (R5.1-R5.35, R8.1-R8.5).

``GeneratedSQL`` is the model's structured output: a single statement using ``%s``
placeholders plus its ordered parameters, capped at 4000 characters (R5.35). The
grain-safety rules (bridge fan-out, incident+action pre-aggregation, zero-action
sentinel, derived week, full GROUP BY, inclusive date range, parameterized
literals) are stated in the system prompt (``sqlgen.prompts``) and demonstrated by
the few-shot pairs; the deterministic firewall then enforces them structurally.

``build_generation_messages`` assembles the model input from the schema context,
the analytics intent and the few-shot pairs. The single model call (and the
``<=2`` firewall submissions per turn) are orchestrated by the graph node (M-13),
which parses the model output into ``GeneratedSQL``.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from kognit_llm.nlu.intent import AnalyticsIntent
from kognit_llm.schema.context_provider import SchemaContext
from kognit_llm.sqlgen.fewshot import FEWSHOT_PAIRS

__all__ = [
    "BoundParam",
    "GeneratedSQL",
    "build_generation_messages",
]

BoundParam = str | int | float | bool

# The generator submits at most this many statements to the firewall per turn:
# the first attempt plus one regeneration after a REJECT (R5.8, R5.34).
MAX_FIREWALL_SUBMISSIONS = 2


class GeneratedSQL(BaseModel):
    """One generated read-only statement with parameterized literals (R5.24, R5.35)."""

    model_config = ConfigDict(extra="forbid")

    statement: Annotated[str, Field(max_length=4000)]
    referenced_tables: list[str]
    referenced_columns: list[str]
    params: list[BoundParam]


def build_generation_messages(
    intent: AnalyticsIntent,
    schema_context: SchemaContext,
    *,
    example_limit: int | None = None,
) -> tuple[str, str]:
    """Return ``(schema_and_examples_block, intent_block)`` for the model call.

    The caller passes the schema/examples block plus the intent block as the
    user-role content of a single ``sql`` completion; the system instruction and
    prompt version come from ``sqlgen.prompts``. ``example_limit`` mirrors the
    schema context provider's example-count reduction (R4.29).
    """
    count = (
        schema_context.example_count
        if example_limit is None
        else min(example_limit, schema_context.example_count)
    )
    examples = FEWSHOT_PAIRS[: max(1, count)]
    example_text = "\n\n".join(
        f"Q: {pair.question}\nSQL:\n{pair.sql}\nparams: {pair.params_note}"
        for pair in examples
    )
    schema_block = (
        "APPROVED SCHEMA CONTEXT:\n"
        f"{schema_context.rendered()}\n\n"
        "EXAMPLES:\n"
        f"{example_text}"
    )
    intent_block = _render_intent(intent)
    return schema_block, intent_block


def _render_intent(intent: AnalyticsIntent) -> str:
    """Render the analytics intent as an unambiguous instruction block."""
    lines = [
        "ANALYTICS INTENT:",
        f"measure: {intent.measure}",
        (
            "time_range (inclusive): "
            f"{intent.time_range.start_date} .. {intent.time_range.end_date}"
        ),
    ]
    if intent.grouping_attributes:
        lines.append("group_by: " + ", ".join(intent.grouping_attributes))
    for f in intent.filters:
        lines.append(
            f"filter: {f.attribute} {f.operator} {f.values} (parameterize values)"
        )
    if intent.ordering is not None:
        lines.append(f"order_by: {intent.ordering.field} {intent.ordering.direction}")
    lines.append(f"limit: {intent.limit}")
    return "\n".join(lines)
