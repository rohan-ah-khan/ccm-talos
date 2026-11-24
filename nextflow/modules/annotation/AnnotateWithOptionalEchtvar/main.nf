process AnnotateWithOptionalEchtvar {
    container params.container

    input:
        tuple val(cohort), path(vcf), path(tbi)
        path annotation_zips

    output:
        tuple val(cohort), path("${vcf.simpleName}_optional_echtvar.vcf.bgz"), path("${vcf.simpleName}_optional_echtvar.vcf.bgz.tbi")

    script:
        def annotation_args = annotation_zips.collect { "-e ${it}" }.join(' ')
        """
        set -euo pipefail

        echtvar anno \
            ${annotation_args} \
            ${vcf} \
            "${vcf.simpleName}_optional_echtvar.vcf.bgz"
        tabix "${vcf.simpleName}_optional_echtvar.vcf.bgz"
        """
}
