# CCM Talos on HPF

This document records changes made in the CCM Talos fork to support deployment
and validation on the SickKids HPF, along with basic setup instructions.

## CCM-specific changes

### External resource downloads

`large_files/gather_files.sh` replaces three unavailable upstream URLs:

- Ensembl release 116 uses the working `release-116/gff3` path.
- nAPOGEE v1.0.0 and MitImpact 3.1.3 use archived copies.

The original URLs remain as comments, and explicit filenames preserve
compatibility with the Talos configuration. These replacements were validated
successfully on HPF.

### Docker and Singularity compatibility

The Docker image includes `git` so `uv` can install the Git-based SVAFotate
dependency. Talos retains its original Python environment at `/talos/.venv/bin`,
which is included in the image's `PATH`. Singularity preserves this `PATH`, so
additional launcher scripts and executable symlinks are not required.

## Setup

Create the initial HPF directories and clone the CCM Talos repository beneath
`repo`:

```bash
export TALOS_BASE=/path/to/talos

mkdir -p \
  "$TALOS_BASE/repo" \
  "$TALOS_BASE/resources/container" \
  "$TALOS_BASE/resources/reference" \
  "$TALOS_BASE/resources/prepared" \
  "$TALOS_BASE/config" \
  "$TALOS_BASE/scripts"

git clone https://github.com/rohan-ah-khan/ccm-talos \
  "$TALOS_BASE/repo/ccm-talos"
cd "$TALOS_BASE/repo/ccm-talos"
```

Talos requires a Singularity image (`.sif`) on HPF. **If an existing `.sif` is available**, 
use that image and skip the container-building steps below. Otherwise,
build the Docker image on a machine with Docker, transfer it, and convert it on HPF.

### Optional: Build a new container

#### 1. Build and check Docker locally

On a machine with Docker, clone the repository:

```bash
git clone https://github.com/rohan-ah-khan/ccm-talos
cd ccm-talos
```

Build and check the Docker archive:

```bash
bash docker/scripts/build_docker.sh /path/to/output
```

#### 2. Transfer the Docker archive to HPF

Create the container directory on HPF:

```bash
mkdir -p /hpf/largeprojects/tgnode/sandbox/rkhan/talos/resources/container
```

From the local machine, transfer the archive:

```bash
scp /path/to/output/talos_12.2.1_amd64.tar \
    YOUR_HPF_LOGIN:/hpf/largeprojects/tgnode/sandbox/rkhan/talos/resources/container/
```

#### 3. Build and validate Singularity on HPF

From the cloned repository in an interactive HPF compute session, run:

```bash
bash docker/scripts/build_singularity.sh \
    /hpf/largeprojects/tgnode/sandbox/rkhan/talos/resources/container
```

A successful build ends with:

```text
[SUCCESS] TALOS Singularity image passed validation.
```

After this validation succeeds, the transferred Docker archive and temporary
Singularity build cache can be removed from HPF:

```bash
rm $TALOS_BASE/resources/container/talos_12.2.1_amd64.tar
rm -r $TALOS_BASE/resources/container/singularity/cache
rm -r $TALOS_BASE/resources/container/singularity/tmp
rmdir $TALOS_BASE/resources/container/singularity
```

### Use an existing Singularity image

If the `.sif` has already been built, note its absolute HPF path. The Docker
build, archive transfer, and Singularity conversion steps do not need to be
repeated for each Talos run.

## Running Talos on HPF

### Reference resource preparation

Run the download script from `resources/reference`. The script writes its
outputs into the current directory, not the directory containing the script.

```bash
export TALOS_BASE=/path/to/talos
cd "$TALOS_BASE/resources/reference"
module load samtools
bash "$TALOS_BASE/repo/ccm-talos/large_files/gather_files.sh"
```

The script can be restarted after an interrupted or failed download. Completed
files are reused, and partial downloads are resumed from their `.part` files.
It creates the reference FASTA index with Samtools and reports any missing or
partial files after its tmux session closes. The script will likely need to be
run more than once because tmux may not be able to create enough panes for all
downloads in a single run. Each rerun skips completed files and continues the
remaining downloads.

The download stage is complete when the script prints:

```text
[SUCCESS] All required Talos resources are present.
```

### Nextflow configuration

`configs/hpf.config` is layered on top of the repository's generic
`nextflow.config`. It selects SLURM and Singularity, points processes to the HPF
`.sif`, and uses writable temporary directories below the Talos working
directory.

All paths in the HPF configuration are derived from the `TALOS_BASE`
environment variable. Set it to the Talos working directory before launching
Nextflow:

```bash
export TALOS_BASE=/path/to/talos
```

### Run annotation preparation

Submit the preparation workflow through Slurm. With no date argument, it uses
the current ClinVar release:

```bash
export TALOS_BASE=/path/to/talos
cd "$TALOS_BASE/repo/ccm-talos"
mkdir -p "$TALOS_BASE/logs/preparation"

sbatch --export=ALL,TALOS_BASE="$TALOS_BASE" scripts/prepare_hpf.slurm
```

The launcher writes prepared resources in `resources/prepared`. To prepare a retrospective ClinVar snapshot, pass an evidence date in `YYYY-MM-DD` format. For example:

```bash
sbatch --export=ALL,TALOS_BASE="$TALOS_BASE" \
  scripts/prepare_hpf.slurm 2023-10-01
```

The date selects the ClinVar snapshot. Supply the same date to the later Talos
analysis to give its evidence retrospective timestamps.


### Run Talos analysis

Talos uses one tab-separated input TSV. For a small-variant run, a
row using a joint VCF looks like:

```text
cohort	path	type	pedigree	config	history
short_read_2026_11	/path/to/talos/cohorts/short_read/2026-11/joint.vcf.bgz	vcf	/path/to/talos/cohorts/short_read/2026-11/cohort.ped	/path/to/talos/config/talos.toml	/path/to/talos/results/short_read/previous/full_results.json
```

The `history` column is optional and can be omitted for the first analysis.
For later analyses, it points to the previous full-results JSON. Additional
cohorts can be provided as additional rows.

The pedigree is also tab-separated, has no header, and contains six required
columns plus an optional seventh HPO column. It can contain multiple families:

```text
FAM001	child_1	father_1	mother_1	1	2	HP:0001250,HP:0001263
FAM001	father_1	0	0	1	1
FAM001	mother_1	0	0	2	1
FAM002	child_2	0	0	2	2	HP:0004322
```

Sample IDs must match the VCF.

The HPF launcher takes the input TSV, output directory, and a run name. It
therefore does not hard-code a production cohort layout:

```bash
export TALOS_BASE=/path/to/talos
mkdir -p "$TALOS_BASE/logs/talos"
cd "$TALOS_BASE/repo/ccm-talos"

sbatch --export=ALL,TALOS_BASE="$TALOS_BASE" scripts/run_hpf.slurm \
  /path/to/talos/cohorts/short_read/2026-11/talos_input.tsv \
  /path/to/talos/results/short_read/2026-11 \
  short_read_2026_11
```
