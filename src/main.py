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

app = create_app(get_settings())
handler = Mangum(app, api_gateway_base_path="/llm")  # R15.14, R15.36
