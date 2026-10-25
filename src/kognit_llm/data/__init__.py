"""Read-only warehouse access: pool, executor, session, probes and error taxonomy.

Import boundary B3: only this package and ``config/secrets.py`` may import
``psycopg`` / ``boto3``. Import boundary B5: no module outside this package
executes SQL.
"""

__all__: list[str] = []
