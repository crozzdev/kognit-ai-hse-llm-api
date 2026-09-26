"""Curated few-shot question/SQL pairs for SQL generation (R4.12).

Between 3 and 10 pairs, each referencing only allow-listed identifiers and each
satisfying every rule of Requirement 6 (single SELECT, allow-listed
tables/columns, parameterized literals, mandatory integer LIMIT, join
predicates). The generator supplies a subset as few-shot content; the schema
context provider may reduce the count to one under the token budget (R4.29).
"""

from dataclasses import dataclass

__all__ = ["FEWSHOT_PAIRS", "FewShotPair"]


@dataclass(frozen=True, slots=True)
class FewShotPair:
    """One curated question and its allow-listed, R6-compliant SQL."""

    question: str
    sql: str
    params_note: str


FEWSHOT_PAIRS: tuple[FewShotPair, ...] = (
    FewShotPair(
        question="How many incidents in a plant in a given month, by severity?",
        sql=(
            "SELECT dim_incident_type.severity AS severity,\n"
            "       SUM(fact_incidents.incident_count) AS incident_count\n"
            "FROM public.fact_incidents\n"
            "JOIN public.dim_date ON dim_date.sk_date = fact_incidents.sk_date\n"
            "JOIN public.dim_location "
            "ON dim_location.sk_location = fact_incidents.sk_location\n"
            "JOIN public.dim_incident_type "
            "ON dim_incident_type.sk_type = fact_incidents.sk_type\n"
            "WHERE dim_date.date BETWEEN %s AND %s\n"
            "  AND dim_location.plant = %s\n"
            "  AND dim_incident_type.category = %s\n"
            "GROUP BY dim_incident_type.severity\n"
            "ORDER BY incident_count DESC, severity ASC\n"
            "LIMIT 1000"
        ),
        params_note="[start_date, end_date, plant_value, 'Incident']",
    ),
    FewShotPair(
        question="How many near misses occurred last year in total?",
        sql=(
            "SELECT SUM(fact_incidents.incident_count) AS incident_count\n"
            "FROM public.fact_incidents\n"
            "JOIN public.dim_date ON dim_date.sk_date = fact_incidents.sk_date\n"
            "JOIN public.dim_incident_type "
            "ON dim_incident_type.sk_type = fact_incidents.sk_type\n"
            "WHERE dim_date.date BETWEEN %s AND %s\n"
            "  AND dim_incident_type.category = %s\n"
            "LIMIT 1000"
        ),
        params_note="[start_date, end_date, 'Near Miss']",
    ),
    FewShotPair(
        question="How many distinct incidents involved a PPE type in a period?",
        sql=(
            "SELECT COUNT(DISTINCT fact_incidents.record_no) AS incident_count\n"
            "FROM public.fact_incidents\n"
            "JOIN public.dim_date ON dim_date.sk_date = fact_incidents.sk_date\n"
            "JOIN public.bridge_incident_ppe "
            "ON bridge_incident_ppe.record_no = fact_incidents.record_no\n"
            "JOIN public.dim_ppe ON dim_ppe.sk_ppe = bridge_incident_ppe.sk_ppe\n"
            "WHERE dim_date.date BETWEEN %s AND %s\n"
            "  AND dim_ppe.ppe_type = %s\n"
            "LIMIT 1000"
        ),
        params_note="[start_date, end_date, ppe_type] (bridge fan-out -> DISTINCT)",
    ),
    FewShotPair(
        question="Incident count by month for a year.",
        sql=(
            "SELECT dim_date.month AS month,\n"
            "       SUM(fact_incidents.incident_count) AS incident_count\n"
            "FROM public.fact_incidents\n"
            "JOIN public.dim_date ON dim_date.sk_date = fact_incidents.sk_date\n"
            "WHERE dim_date.date BETWEEN %s AND %s\n"
            "GROUP BY dim_date.month\n"
            "ORDER BY dim_date.month ASC\n"
            "LIMIT 1000"
        ),
        params_note="[start_date, end_date]",
    ),
)
