import os

import boto3
import psycopg

# ── Configuration ─────────────────────────────────────────────────────────────


def get_parameter(name: str, with_decryption: bool = True) -> str:
    ssm = boto3.client("ssm", region_name="us-east-1")
    return ssm.get_parameter(Name=name, WithDecryption=with_decryption)["Parameter"][
        "Value"
    ]


# Call once at cold start (outside handler) for performance, these are degfined only
# in AWS Lambda environment

if "is_in_aws_lambda" in os.environ:
    DB_HOST = get_parameter("/kognit/db/POSTGRES_HOST")
    DB_NAME = get_parameter("/kognit/db/POSTGRES_DB")
    DB_USER = get_parameter("/kognit/db/POSTGRES_USER")
    DB_PASS = get_parameter("/kognit/db/POSTGRES_PASSWORD")
    DB_PORT = get_parameter("/kognit/db/POSTGRES_PORT")


def check_postgres() -> dict:
    try:
        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            connect_timeout=5,
        )
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            row = cur.fetchone()
            if row is None:
                raise Exception("No result returned from PostgreSQL")
            version = row[0]
        conn.close()
        return {"status": "ok", "postgres_version": version}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
