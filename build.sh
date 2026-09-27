#!/bin/bash
set -e  # Exit immediately if a command fails

# Get the absolute path of the current directory (your repo root)
PROJECT_ROOT=$PWD
ZIP_NAME="kognit-ai-hse-llm-api.zip"
ZIP_PATH="$PROJECT_ROOT/$ZIP_NAME"

echo "Starting build process..."

# 1. Clean up any old builds
rm -rf packages
rm -f "$ZIP_PATH"

# 2. Export production-only dependencies
uv export --frozen --no-dev --no-editable -o requirements.txt

# 3. Install Linux-compatible dependencies into the "package" folder
uv pip install \
   --no-installer-metadata \
   --no-compile-bytecode \
   --python-platform x86_64-manylinux2014 \
   --python 3.13 \
   --target packages \
   -r requirements.txt

# 4. Zip the dependencies from inside the package folder
# (We use the absolute path to save it right back into the repo root)
cd packages
zip -r "$ZIP_PATH" .
cd ..

# 5. Add the full application tree (fixes R-13; preserves the src/ prefix so the
#    Lambda handler stays src.main.handler and no infrastructure change is needed)
zip -r "$ZIP_PATH" src \
  -x '*__pycache__*' '*.pyc' '*.pyo' '*/.pytest_cache/*'

# 6. Verify the artifact imports (R15.40)
WORK="$(mktemp -d)"
unzip -q "$ZIP_PATH" -d "$WORK"
PYTHONPATH="$WORK" python3 - <<'PY'
import importlib

mod = importlib.import_module("src.main")  # executes every transitive import
assert callable(mod.handler), "handler is not callable"
print("artifact import check passed")
PY
rm -rf "$WORK"

# 7. Enforce the size gate (R15.13, R15.34)
UNCOMP=$(unzip -Zt "$ZIP_PATH" | awk '{print $3}')
COMP=$(stat -c%s "$ZIP_PATH")
python3 - "$UNCOMP" "$COMP" <<'PY'
import sys

unc, comp = int(sys.argv[1]), int(sys.argv[2])
for measured, limit, label in (
    (unc, 250 * 1024 * 1024, "uncompressed"),
    (comp, 50 * 1024 * 1024, "compressed"),
):
    if measured > limit:
        raise SystemExit(f"artifact {label} size {measured} exceeds limit {limit}")
print(f"artifact sizes ok: uncompressed={unc} compressed={comp}")
PY

# 8. Clean up temporary files
rm -rf packages
rm requirements.txt

echo "Build complete! File saved successfully to:"
echo "$ZIP_PATH"