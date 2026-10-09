"""Star-schema join graph handed to the SQL generator (R4.11).

Encodes the two edge kinds of the design's join graph:

- ``surrogate`` edges: a fact's ``sk_*`` foreign key joins a dimension's matching
  ``sk_*`` primary key (solid edges).
- ``degenerate`` edges: the ``record_no`` degenerate dimension joins incidents to
  their corrective actions and to the two bridge tables (dashed edges).

The generator consults this graph to build only allow-listed joins and to apply
the grain-safety rules (bridge fan-out, action fan-out) of the design.
"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["JOIN_GRAPH", "JoinEdge", "edges_from", "edges_touching"]


@dataclass(frozen=True, slots=True)
class JoinEdge:
    """One join edge between two allow-listed relations."""

    left: str
    right: str
    left_key: str
    right_key: str
    kind: Literal["surrogate", "degenerate"]


# Surrogate-key edges from the fact tables to their conformed dimensions, plus
# the record_no degenerate-dimension edges. Direction is informational only;
# joins are symmetric. Ordered as in the design's join-graph diagram.
JOIN_GRAPH: tuple[JoinEdge, ...] = (
    # fact_incidents -> dimensions (surrogate keys)
    JoinEdge("fact_incidents", "dim_date", "sk_date", "sk_date", "surrogate"),
    JoinEdge(
        "fact_incidents", "dim_location", "sk_location", "sk_location", "surrogate"
    ),
    JoinEdge(
        "fact_incidents", "dim_incident_type", "sk_type", "sk_type", "surrogate"
    ),
    JoinEdge("fact_incidents", "dim_shift", "sk_shift", "sk_shift", "surrogate"),
    JoinEdge("fact_incidents", "dim_cause", "sk_cause", "sk_cause", "surrogate"),
    JoinEdge("fact_incidents", "dim_status", "sk_status", "sk_status", "surrogate"),
    JoinEdge(
        "fact_incidents", "dim_equipment", "sk_equipment", "sk_equipment", "surrogate"
    ),
    JoinEdge(
        "fact_incidents",
        "dim_high_risk_area",
        "sk_high_risk_area",
        "sk_high_risk_area",
        "surrogate",
    ),
    # fact_actions -> dimensions (surrogate keys)
    JoinEdge(
        "fact_actions", "dim_action_details", "sk_action", "sk_action", "surrogate"
    ),
    JoinEdge("fact_actions", "dim_date", "sk_date", "sk_date", "surrogate"),
    JoinEdge("fact_actions", "dim_location", "sk_location", "sk_location", "surrogate"),
    # record_no degenerate-dimension edges (dashed)
    JoinEdge("fact_incidents", "fact_actions", "record_no", "record_no", "degenerate"),
    JoinEdge(
        "fact_incidents", "bridge_incident_ppe", "record_no", "record_no", "degenerate"
    ),
    JoinEdge(
        "fact_incidents",
        "bridge_incident_injury",
        "record_no",
        "record_no",
        "degenerate",
    ),
    # bridges -> their dimensions (surrogate keys)
    JoinEdge("bridge_incident_ppe", "dim_ppe", "sk_ppe", "sk_ppe", "surrogate"),
    JoinEdge(
        "bridge_incident_injury", "dim_injury", "sk_injury", "sk_injury", "surrogate"
    ),
)


def edges_from(table: str) -> tuple[JoinEdge, ...]:
    """Return the edges whose left endpoint is ``table``."""
    return tuple(edge for edge in JOIN_GRAPH if edge.left == table)


def edges_touching(table: str) -> tuple[JoinEdge, ...]:
    """Return every edge with ``table`` as either endpoint."""
    return tuple(
        edge for edge in JOIN_GRAPH if table in (edge.left, edge.right)
    )
