process DownloadPanelApp {
    container params.container

    input:
        val timestamp
        val evidence_date

    output:
        path "panelapp_${timestamp}.json", emit: combined
        path "panelapp_${timestamp}.json.bk", emit: panelapp_backup

    script:
        def evidence_arg = evidence_date ? "--evidence-date ${evidence_date}" : ''
        """
        set -euo pipefail

        python -m talos.download_panelapp --output panelapp_${timestamp}.json ${evidence_arg}
        """
}
