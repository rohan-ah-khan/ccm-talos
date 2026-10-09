#!/usr/bin/env bash
set -euo pipefail

# Usage: bash docker/scripts/build_docker.sh /path/to/output

OUTPUT_DIR="$1"
mkdir -p "$OUTPUT_DIR"

# Build Docker image from repository root
docker build \
    --platform linux/amd64 \
    -f docker/Dockerfile \
    -t talos:12.2.1 \
    .

# Check installed tools
docker run --rm --platform linux/amd64 talos:12.2.1 bash -euc '
    python -c "import talos, cyvcf2"
    command -v run_workflow
    command -v bcftools
    command -v tabix
    command -v echtvar
    command -v svafotate
'

# Export Docker image
docker save -o "$OUTPUT_DIR/talos_12.2.1_amd64.tar" talos:12.2.1

echo "Saved to $OUTPUT_DIR/talos_12.2.1_amd64.tar"
