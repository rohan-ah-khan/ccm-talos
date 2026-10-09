#!/usr/bin/env bash
set -euo pipefail

# Usage: bash docker/scripts/build_singularity.sh /path/to/containers

OUTPUT_DIR="$1"

# Load Singularity on HPF
module load Singularity/3.11.3

# Create directories
mkdir -p "$OUTPUT_DIR" \
    "$OUTPUT_DIR/../singularity/cache" \
    "$OUTPUT_DIR/../singularity/tmp"

export SINGULARITY_CACHEDIR="$OUTPUT_DIR/../singularity/cache"
export SINGULARITY_TMPDIR="$OUTPUT_DIR/../singularity/tmp"

# Build Singularity image from Docker archive
singularity build \
    "$OUTPUT_DIR/talos_12.2.1.sif" \
    "docker-archive://$OUTPUT_DIR/talos_12.2.1_amd64.tar"

# Check installed tools
singularity exec --cleanenv "$OUTPUT_DIR/talos_12.2.1.sif" bash -euc '
    python -c "import talos, cyvcf2"
    run_workflow --help >/dev/null
    bcftools --version
    tabix --version
    echtvar --version
    svafotate annotate -h >/dev/null
'

echo "Saved to $OUTPUT_DIR/talos_12.2.1.sif"
