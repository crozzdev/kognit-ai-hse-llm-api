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

# 5. Add the full application source tree into the same zip file
#    (this service uses the src/kognit_llm/ package, so we zip the whole `src`
#    tree instead of `src/*.py`, which would leave the package out)
zip -r "$ZIP_PATH" src -x '*__pycache__*' '*.pyc' '*.pyo'

# 6. Clean up temporary files
rm -rf packages
rm requirements.txt

echo "Build complete! File saved successfully to:"
echo "$ZIP_PATH"
