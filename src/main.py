"""AWS Lambda entry module: the FastAPI app and the Mangum handler.

Lambda imports this module as ``src.main`` (handler ``src.main.handler``), and the
deployment artifact keeps the ``src/`` layout shared with the other services. The
``kognit_llm`` package uses absolute imports (``from kognit_llm...``), so this
module puts its own directory (``src/``) on ``sys.path`` before importing the
package. That makes the imports resolve both in Lambda (where only the zip root
is on the path) and locally (where ``pyproject`` already adds ``.`` and ``src``).
"""

import os
import sys

# Ensure the directory holding this file (``src/``) is importable, so the
# package's absolute imports resolve regardless of the invocation root.
sys.path.insert(0, os.path.dirname(__file__))

from mangum import Mangum  # noqa: E402  (import after the sys.path bootstrap)

from kognit_llm.api.app import create_app  # noqa: E402
from kognit_llm.config.settings import get_settings  # noqa: E402

# SSM parameter name -> KOGNIT_LLM_* environment variable, resolved at cold start
# when running in Lambda (the same pattern the other services use for their
# config). The model values are non-secret (a provider name, a model ARN and a
# region); the Bedrock credential itself comes from the Lambda execution role.
# The warehouse values reuse the shared /kognit/db/POSTGRES_* parameters that the
# statistics service also reads, so the LLM connects to the same warehouse.
_SSM_ENV_MAP = {
    "/kognit/llm/PROVIDER": "KOGNIT_LLM_MODEL_PROVIDER",
    "/kognit/llm/MODEL_ID": "KOGNIT_LLM_MODEL_ID",
    "/kognit/llm/REGION": "KOGNIT_LLM_AWS_REGION",
    # Cross-account Bedrock credentials: Bedrock is enabled only in the personal
    # account, while this Lambda runs in another account. These SecureString keys
    # let the Bedrock client authenticate against the account that owns the model.
    "/kognit/llm/AWS_ACCESS_KEY_ID": "KOGNIT_LLM_BEDROCK_ACCESS_KEY_ID",
    "/kognit/llm/AWS_SECRET_ACCESS_KEY": "KOGNIT_LLM_BEDROCK_SECRET_ACCESS_KEY",
    "/kognit/db/POSTGRES_HOST": "KOGNIT_LLM_DB_HOST",
    "/kognit/db/POSTGRES_DB": "KOGNIT_LLM_DB_NAME",
    "/kognit/db/POSTGRES_PORT": "KOGNIT_LLM_DB_PORT",
    "/kognit/db/POSTGRES_USER": "KOGNIT_LLM_DB_USER",
    "/kognit/db/POSTGRES_PASSWORD": "KOGNIT_LLM_DB_PASSWORD",
}


def _load_config_from_ssm() -> None:
    """Populate KOGNIT_LLM_* env vars from SSM when running in Lambda.

    Runs only inside the Lambda runtime (detected via ``AWS_LAMBDA_FUNCTION_NAME``),
    so local and CI runs read configuration from the environment exactly as before
    (R15.16). It never overwrites a value already set in the environment, and a
    missing parameter or an SSM/transport error is swallowed so the service still
    starts and degrades through the normal health path (R15.24).
    """
    if "AWS_LAMBDA_FUNCTION_NAME" not in os.environ:
        return
    region = os.environ.get("KOGNIT_LLM_AWS_REGION") or os.environ.get(
        "AWS_REGION", "us-east-1"
    )
    try:
        import boto3

        ssm = boto3.client("ssm", region_name=region)
        for param_name, env_var in _SSM_ENV_MAP.items():
            if os.environ.get(env_var):
                continue  # an explicit env var wins over SSM
            try:
                value = ssm.get_parameter(Name=param_name, WithDecryption=True)[
                    "Parameter"
                ]["Value"]
            except Exception:
                continue  # missing/unreadable parameter is non-fatal
            if value:
                os.environ[env_var] = value
    except Exception:
        # boto3 unavailable or client build failed: leave the environment as-is.
        return
    # The shared warehouse is reached the same way the statistics service reaches
    # it (no enforced TLS); default the LLM's sslmode to match unless overridden.
    os.environ.setdefault("KOGNIT_LLM_DB_SSLMODE", "disable")


_load_config_from_ssm()

app = create_app(get_settings())
handler = Mangum(app, api_gateway_base_path="/llm")  # R15.14, R15.36
