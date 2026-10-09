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

Clone the CCM Talos repository on HPF:

```bash
git clone https://github.com/rohan-ah-khan/ccm-talos
cd ccm-talos
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

Create a container directory on HPF (example location):

```bash
mkdir -p /path/to/containers
```

From the local machine, transfer the archive:

```bash
scp /path/to/output/talos_12.2.1_amd64.tar \
    YOUR_HPF_LOGIN:/path/to/containers/
```

#### 3. Build and check Singularity on HPF

From the cloned repository in an interactive HPF compute session, run:

```bash
bash docker/scripts/build_singularity.sh \
    /hpf/largeprojects/tgnode/sandbox/rkhan/talos_attempt/containers
```

### Use an existing Singularity image

If the `.sif` has already been built, note its absolute HPF path. The Docker
build, archive transfer, and Singularity conversion steps do not need to be
repeated for each Talos run.

## Running Talos on HPF

*To be documented after container setup is finalized. The following is just a skeleton*

### Reference resource preparation

- Download or stage Talos reference resources using the CCM fork's resource scripts.
- Record the shared reference and annotation paths used by the workflow.

### Nextflow configuration

- Configure Singularity and the SLURM executor.
- Point relevant processes to the chosen `.sif` image.
- Configure writable temporary directories for Hail/Spark and suitable task resources.

### Run annotation preparation

- Run `preparation.nf` with the HPF configuration and review its logs and outputs.

### Run Talos analysis

- Document cohort inputs, Talos execution commands, result locations, and validation checks.
