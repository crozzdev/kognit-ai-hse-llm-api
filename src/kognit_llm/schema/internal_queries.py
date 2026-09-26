"""Statically defined internal queries (R7.35, R4.14, R4.25-R4.27, R7.16, R7.25).

These four literals are the only SQL in the service not produced by the
generator, and the only SQL the executor accepts without an ``ADMIT`` verdict.
Q2 and Q3 reference ``information_schema`` / catalog helper functions that the
firewall forbids; that is deliberate — they are service-owned, read-only literals
executed through a private executor path, never through ``execute_admitted``.

``Q4_DIMENSION_VALUES_TEMPLATE`` has ``{schema}``, ``{table}`` and ``{column}``
interpolated only from the allow-list, never from user input, and its ``LIMIT``
is ``dimension_value_max + 1`` so a "not enumerated" outcome is detectable.
"""

__all__ = [
    "Q1_LIVENESS",
    "Q2_ALLOWLIST_VERIFICATION",
    "Q3_PRIVILEGE_VERIFICATION",
    "Q4_DIMENSION_VALUES_TEMPLATE",
]

# Q1 liveness (R7.25).
Q1_LIVENESS = "SELECT 1;"

# Q2 allow-list verification (R4.14). Parameters: schema, then a table-name array.
Q2_ALLOWLIST_VERIFICATION = """
SELECT c.table_name, c.column_name, c.data_type
FROM information_schema.columns AS c
WHERE c.table_schema = %s
  AND c.table_name = ANY(%s);
"""

# Q3 privilege verification (R7.16): reports any write privilege held directly or
# through role membership, on any allow-listed relation or on the approved schema.
# Parameters: schema (for has_schema_privilege), then a relation-name text array.
Q3_PRIVILEGE_VERIFICATION = """
SELECT
  bool_or(has_table_privilege(t.relname, 'INSERT'))     AS has_insert,
  bool_or(has_table_privilege(t.relname, 'UPDATE'))     AS has_update,
  bool_or(has_table_privilege(t.relname, 'DELETE'))     AS has_delete,
  bool_or(has_table_privilege(t.relname, 'TRUNCATE'))   AS has_truncate,
  bool_or(has_table_privilege(t.relname, 'REFERENCES')) AS has_references,
  bool_or(has_table_privilege(t.relname, 'TRIGGER'))    AS has_trigger,
  bool_or(has_schema_privilege(%s, 'CREATE'))           AS has_create
FROM unnest(%s::text[]) AS t(relname);
"""

# Q4 dimension-value enumeration (R4.25-R4.27). Issued once per enumerable
# attribute; identifiers come only from the allow-list. Parameter: the row limit
# (dimension_value_max + 1).
Q4_DIMENSION_VALUES_TEMPLATE = """
SELECT DISTINCT {column} AS value
FROM {schema}.{table}
WHERE {column} IS NOT NULL
ORDER BY 1
LIMIT %s;
"""
