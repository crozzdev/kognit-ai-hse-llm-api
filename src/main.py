"""AWS Lambda entry module: the FastAPI app and the Mangum handler.

This is the only module with a dual-root import shim (R15.27): it must import
whether the package root is the repository root or the ``src`` directory.
Everything under ``kognit_llm/**`` uses relative imports and is root-agnostic.
"""

from mangum import Mangum

try:  # package root = repository root
    from src.kognit_llm.api.app import create_app
    from src.kognit_llm.config.settings import get_settings
except ImportError:  # package root = src directory
    from kognit_llm.api.app import create_app
    from kognit_llm.config.settings import get_settings

app = create_app(get_settings())
handler = Mangum(app, api_gateway_base_path="/llm")  # R15.14, R15.36
