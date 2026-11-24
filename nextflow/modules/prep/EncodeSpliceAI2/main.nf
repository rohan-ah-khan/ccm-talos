process EncodeSpliceAI2 {
    container params.container

    publishDir params.processed_annotations, mode: 'copy', pattern: '*.zip'

    input:
        path tsv
        path echtvar_config
        path base_vcf_header

    output:
        tuple path('spliceai2.vcf.gz'), path('spliceai2.zip')

    script:
        """
        set -euo pipefail

        {
            grep -vE '^##INFO=|^#CHROM' ${base_vcf_header}
            printf '%s\n' \
                '##INFO=<ID=spliceai2_strand,Number=1,Type=String,Description="SpliceAI2 transcript strand">' \
                '##INFO=<ID=spliceai2_donor_gain_score,Number=1,Type=Float,Description="SpliceAI2 donor gain delta score">' \
                '##INFO=<ID=spliceai2_donor_gain_distance,Number=1,Type=Integer,Description="SpliceAI2 donor gain signed distance">' \
                '##INFO=<ID=spliceai2_donor_loss_score,Number=1,Type=Float,Description="SpliceAI2 donor loss delta score">' \
                '##INFO=<ID=spliceai2_donor_loss_distance,Number=1,Type=Integer,Description="SpliceAI2 donor loss signed distance">' \
                '##INFO=<ID=spliceai2_acceptor_gain_score,Number=1,Type=Float,Description="SpliceAI2 acceptor gain delta score">' \
                '##INFO=<ID=spliceai2_acceptor_gain_distance,Number=1,Type=Integer,Description="SpliceAI2 acceptor gain signed distance">' \
                '##INFO=<ID=spliceai2_acceptor_loss_score,Number=1,Type=Float,Description="SpliceAI2 acceptor loss delta score">' \
                '##INFO=<ID=spliceai2_acceptor_loss_distance,Number=1,Type=Integer,Description="SpliceAI2 acceptor loss signed distance">' \
                '##INFO=<ID=spliceai2_summary_score,Number=1,Type=Float,Description="Maximum of the four SpliceAI2 delta scores">'
            printf '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
            gzip -cd ${tsv} | awk -F '\t' '
                BEGIN { OFS="\t" }
                NR > 1 {
                    info = "spliceai2_strand=" \$5 \
                        ";spliceai2_donor_gain_score=" \$6 \
                        ";spliceai2_donor_gain_distance=" \$7 \
                        ";spliceai2_donor_loss_score=" \$8 \
                        ";spliceai2_donor_loss_distance=" \$9 \
                        ";spliceai2_acceptor_gain_score=" \$10 \
                        ";spliceai2_acceptor_gain_distance=" \$11 \
                        ";spliceai2_acceptor_loss_score=" \$12 \
                        ";spliceai2_acceptor_loss_distance=" \$13 \
                        ";spliceai2_summary_score=" \$14
                    print \$1, \$2, ".", \$3, \$4, ".", "PASS", info
                }
            '
        } | bgzip -c > spliceai2.vcf.gz

        echtvar encode spliceai2.zip ${echtvar_config} spliceai2.vcf.gz
        """
}
