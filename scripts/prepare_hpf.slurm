#!/usr/bin/env bash
#SBATCH --job-name=talos_prepare
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=48:00:00
#SBATCH --output=/hpf/largeprojects/tgnode/sandbox/rkhan/talos/logs/preparation/%x.%j.out
#SBATCH --error=/hpf/largeprojects/tgnode/sandbox/rkhan/talos/logs/preparation/%x.%j.err

set -euo pipefail

: "${TALOS_BASE:?Set TALOS_BASE before submitting this job}"

EVIDENCE_DATE="${1:-}"
REPOSITORY="$TALOS_BASE/repo/ccm-talos"
RUN_LABEL="${EVIDENCE_DATE:-current}"
RUN_TMP="$TALOS_BASE/tmp/preparation/$RUN_LABEL"
WORK_DIR="$RUN_TMP/work"
export TALOS_SPARK_DIR="$RUN_TMP/spark"
RUN_DATE=$(date '+%Y-%m-%d')
LOG_DIR="$TALOS_BASE/logs/preparation"

if [[ -n "$EVIDENCE_DATE" && ! "$EVIDENCE_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Evidence date must use YYYY-MM-DD format: $EVIDENCE_DATE" >&2
    exit 2
fi

mkdir -p \
    "$LOG_DIR" \
    "$WORK_DIR" \
    "$TALOS_SPARK_DIR"

module load nextflow/26.04.6
module load Singularity/3.11.3

cd "$REPOSITORY"

NEXTFLOW_ARGS=(
    -log "$LOG_DIR/nextflow_${RUN_LABEL}_${RUN_DATE}_${SLURM_JOB_ID}.log"
    run preparation.nf
    -c configs/hpf.config
    -work-dir "$WORK_DIR"
)

if [[ -n "$EVIDENCE_DATE" ]]; then
    NEXTFLOW_ARGS+=(--evidence_date "$EVIDENCE_DATE")
fi

nextflow "${NEXTFLOW_ARGS[@]}"

EVIDENCE_MONTH="${EVIDENCE_DATE:0:7}"
if [[ -z "$EVIDENCE_MONTH" ]]; then
    EVIDENCE_MONTH=$(date '+%Y-%m')
fi

test -d "$TALOS_BASE/resources/prepared/clinvarbitration_${EVIDENCE_MONTH}.ht"
test -d "$TALOS_BASE/resources/prepared/clinvarbitration_${EVIDENCE_MONTH}.pm5.ht"
test -s "$TALOS_BASE/resources/prepared/panelapp_$(date '+%Y-%m').json"
test -s "$TALOS_BASE/resources/prepared/mane.json"
test -s "$TALOS_BASE/resources/prepared/alphamissense.zip"

rm -r "$RUN_TMP"

echo "[SUCCESS] Talos preparation outputs are present for ClinVar ${EVIDENCE_MONTH}."
echo "[SUCCESS] Removed temporary preparation work: $RUN_TMP"
