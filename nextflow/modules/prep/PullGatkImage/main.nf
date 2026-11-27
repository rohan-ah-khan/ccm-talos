process PullGatkImage {
    // Runs on the host, not in a container: the pull needs the host's singularity, which the Talos image lacks.
    // Used when set in configs/hpf.config
    container null

    publishDir file(params.gatk_container).parent, mode: 'move'

    input:
        val image       
        val sif_name    

    output:
        path "${sif_name}"

    script:
        """
        set -euo pipefail

        # Singularity's temp and cache inside this task's work dir.
        mkdir -p singularity_tmp singularity_cache
        export SINGULARITY_TMPDIR=\$PWD/singularity_tmp
        export SINGULARITY_CACHEDIR=\$PWD/singularity_cache

        singularity pull ${sif_name} ${image}

        # the image must run GATK before it is published
        singularity exec ${sif_name} gatk --version

        rm -rf singularity_tmp singularity_cache
        """
}
