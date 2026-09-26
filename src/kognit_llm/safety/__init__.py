"""Non-LLM safety layer: scope guard and deny-by-default query firewall.

Import boundary B1: this package must not import ``providers/**``, ``data/**``,
``psycopg``, ``boto3`` or any HTTP client.
"""

__all__: list[str] = []
