process DownloadClinVarFiles {
    container params.container

    errorStrategy {'retry'}
    maxRetries 3

    input:
        val clinvar_month
        val evidence_date

    output:
        path "submissions_${clinvar_month}.txt.gz", emit: submissions
        path "variants_${clinvar_month}.txt.gz", emit: variants

    script:
        def archive_year = clinvar_month.substring(0, 4)
        def archive_url = 'https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive'
        if (evidence_date) {
            // NCBI currently keeps older releases in year subdirectories, while newer
            // releases are stored at the archive root, so try both layouts.
            """
            set -euo pipefail

            wget '${archive_url}/submission_summary_${clinvar_month}.txt.gz' -O submissions_${clinvar_month}.txt.gz || \
                wget '${archive_url}/${archive_year}/submission_summary_${clinvar_month}.txt.gz' -O submissions_${clinvar_month}.txt.gz
            wget '${archive_url}/variant_summary_${clinvar_month}.txt.gz' -O variants_${clinvar_month}.txt.gz || \
                wget '${archive_url}/${archive_year}/variant_summary_${clinvar_month}.txt.gz' -O variants_${clinvar_month}.txt.gz

            gzip -t submissions_${clinvar_month}.txt.gz
            gzip -t variants_${clinvar_month}.txt.gz
            """
        } else {
            """
            set -euo pipefail

            wget '${params.submission_summary}' -O submissions_${clinvar_month}.txt.gz
            wget '${params.variant_summary}' -O variants_${clinvar_month}.txt.gz
            wget '${params.submission_summary}.md5' -O submissions.md5
            wget '${params.variant_summary}.md5' -O variants.md5
            sed -E 's/[[:space:]].*/  submissions_${clinvar_month}.txt.gz/' submissions.md5 > check.md5
            sed -E 's/[[:space:]].*/  variants_${clinvar_month}.txt.gz/' variants.md5 >> check.md5
            md5sum --check check.md5
            """
        }
}
