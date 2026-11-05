#!/usr/bin/env bash
#SBATCH --job-name=talos_run
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=48:00:00
#SBATCH --output=/hpf/largeprojects/tgnode/sandbox/rkhan/talos/logs/talos/%x.%j.out
#SBATCH --error=/hpf/largeprojects/tgnode/sandbox/rkhan/talos/logs/talos/%x.%j.err

set -euo pipefail

: "${TALOS_BASE:?Set TALOS_BASE before submitting this job}"

if (( $# < 3 || $# > 4 )); then
    echo "Usage: $0 INPUT_TSV OUTPUT_DIR RUN_NAME [EVIDENCE_DATE]" >&2
    exit 2
fi

INPUT_TSV="$1"
OUTPUT_DIR="$2"
RUN_NAME="$3"
EVIDENCE_DATE="${4:-}"

if [[ ! "$RUN_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "RUN_NAME may contain only letters, numbers, periods, underscores, and hyphens" >&2
    exit 2
fi

if [[ -n "$EVIDENCE_DATE" && ! "$EVIDENCE_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Evidence date must use YYYY-MM-DD format: $EVIDENCE_DATE" >&2
    exit 2
fi

REPOSITORY="$TALOS_BASE/repo/ccm-talos"
RUN_TMP="$TALOS_BASE/tmp/runs/$RUN_NAME"
WORK_DIR="$RUN_TMP/work"
export TALOS_SPARK_DIR="$RUN_TMP/spark"
LOG_DIR="$TALOS_BASE/logs/talos"
RUN_DATE=$(date '+%Y-%m-%d')

test -s "$INPUT_TSV"

mkdir -p \
    "$OUTPUT_DIR" \
    "$WORK_DIR" \
    "$TALOS_SPARK_DIR"

module load nextflow/26.04.6
module load Singularity/3.11.3

cd "$REPOSITORY"

NEXTFLOW_ARGS=(
    -log "$LOG_DIR/nextflow_${RUN_NAME}_${SLURM_JOB_ID}.log"
    run main.nf
    -c configs/hpf.config
    -work-dir "$WORK_DIR"
    --input_tsv "$INPUT_TSV"
    -output-dir "$OUTPUT_DIR"
)

if [[ -n "$EVIDENCE_DATE" ]]; then
    NEXTFLOW_ARGS+=(--evidence_date "$EVIDENCE_DATE")
fi

nextflow "${NEXTFLOW_ARGS[@]}"

mapfile -t COHORTS < <(awk -F'\t' 'NR > 1 && $1 != "" {print $1}' "$INPUT_TSV")
if (( ${#COHORTS[@]} == 0 )); then
    echo "No cohorts found in $INPUT_TSV" >&2
    exit 1
fi

for cohort in "${COHORTS[@]}"; do
    result_dir="$OUTPUT_DIR/${cohort}_outputs"
    test -s "$result_dir/${cohort}_full_results_${RUN_DATE}.json"
    test -s "$result_dir/${cohort}_report_${RUN_DATE}.html"
    test -s "$result_dir/${cohort}_panelapp.json"
    test -s "$result_dir/${cohort}_small_variants_labelled.vcf.bgz"
    test -s "$result_dir/${cohort}_small_variants_labelled.vcf.bgz.tbi"
done

rm -r "$RUN_TMP"

echo "[SUCCESS] Talos outputs passed validation for: ${COHORTS[*]}"
echo "[SUCCESS] Removed temporary Talos work: $RUN_TMP"
