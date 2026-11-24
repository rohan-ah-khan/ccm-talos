process EncodeAlphaGenome {
    container params.container

    publishDir params.processed_annotations, mode: 'copy', pattern: '*.zip'

    input:
        path tsv
        path echtvar_config
        path base_vcf_header

    output:
        tuple path('alphagenome.vcf.gz'), path('alphagenome.zip')

    script:
        """
        set -euo pipefail

        {
            grep -vE '^##INFO=|^#CHROM' ${base_vcf_header}
            printf '%s\n' \
                '##INFO=<ID=avi_score,Number=1,Type=Float,Description="AlphaGenome AVI PHRED score">'
            printf '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
            gzip -cd ${tsv} | awk -F '\t' '
                BEGIN { OFS="\t" }
                NR > 1 {
                    print \$1, \$2, ".", \$3, \$4, ".", "PASS", "avi_score=" \$6
                }
            '
        } | bgzip -c > alphagenome.vcf.gz

        echtvar encode alphagenome.zip ${echtvar_config} alphagenome.vcf.gz
        """
}
