# CCM Talos on HPF

This document records changes made in the CCM Talos fork to support deployment
and validation on the SickKids HPF.

## CCM-specific changes

### External resource downloads

`large_files/gather_files.sh` replaces three unavailable upstream URLs:

- Ensembl release 116 uses the working `release-116/gff3` path.
- nAPOGEE v1.0.0 and MitImpact 3.1.3 use archived copies.

The original URLs remain as comments, and explicit filenames preserve
compatibility with the Talos configuration. These replacements were validated
successfully on HPF.
