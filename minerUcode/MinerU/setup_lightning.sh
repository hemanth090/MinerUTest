#!/usr/bin/env bash
set -euo pipefail

echo "Installing dependencies..."
pip install -r "$(dirname "$0")/requirements.txt"

echo "Patching transformers generation config..."
GCFILE=$(python3 -c "import transformers.generation.configuration_utils as gc; import pathlib; print(pathlib.Path(gc.__file__))")
sed -i 's/decoder_config_dict = decoder_config.to_dict()/decoder_config_dict = decoder_config.to_dict() if hasattr(decoder_config, "to_dict") else decoder_config/' "$GCFILE"

echo "Setup complete. Run: bash run_hybrid.sh"
