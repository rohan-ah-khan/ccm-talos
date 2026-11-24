"""Build OMIM disease panels from HPO annotations and merge them into PanelApp."""

from __future__ import annotations

import csv
import gzip
import json
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from talos.models import DownloadedPanelApp, DownloadedPanelAppGene, DownloadedPanelAppPanel, HpoTerm, PanelShort

PANEL_ID_OFFSET = 900_000_000
OMIM_CONFIDENCE = 4
ASSOCIATION_DATE = '1970-01-01'
PRIMARY_CHROMS = {str(chrom) for chrom in range(1, 23)} | {'X', 'Y', 'M'}

HPO_RELEASES_URL = 'https://api.github.com/repos/obophenotype/human-phenotype-ontology/releases?per_page=30'
NCBI_GENE2ENSEMBL_URL = 'https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene2ensembl.gz'
ENSEMBL_VERSION_URL = 'https://ftp.ensembl.org/pub/VERSION'
ENSEMBL_GTF_TEMPLATE = 'https://ftp.ensembl.org/pub/release-{release}/gtf/homo_sapiens/Homo_sapiens.GRCh38.{release}.gtf.gz'

MOI_AUTOSOMAL_DOMINANT = 'monoallelic, autosomal or pseudoautosomal'
MOI_AUTOSOMAL_RECESSIVE = 'biallelic, autosomal or pseudoautosomal'
MOI_AUTOSOMAL_BOTH = 'both monoallelic and biallelic, autosomal or pseudoautosomal'
MOI_X_RECESSIVE = 'x-linked: hemizygous mutation in males, biallelic mutations in females'
MOI_X_DOMINANT = (
    'x-linked: hemizygous mutation in males, monoallelic mutations in females may cause disease '
    '(may be less severe, later onset than males)'
)
MOI_MITOCHONDRIAL = 'mitochondrial'
MOI_PATERNALLY_IMPRINTED = 'monoallelic, autosomal or pseudoautosomal, paternally imprinted (maternal allele expressed)'
MOI_MATERNALLY_IMPRINTED = 'monoallelic, autosomal or pseudoautosomal, maternally imprinted (paternal allele expressed)'

MOI_TERM_CLASSES = {
    'HP:0000006': 'AD',
    'HP:0000007': 'AR',
    'HP:0001419': 'XLR',
    'HP:0001423': 'XLD',
    'HP:0001427': 'MT',
    'HP:0012274': 'AD_PATERNALLY_IMPRINTED',
    'HP:0012275': 'AD_MATERNALLY_IMPRINTED',
    'HP:0034340': 'AD',
    'HP:0034341': 'AR',
}
GENERIC_X_LINKED_TERM = 'HP:0001417'
INHERITANCE_QUALIFIERS = {
    'HP:0001442',  # somatic mosaicism
    'HP:0001466',  # contiguous gene syndrome
    'HP:0001470',  # sex-limited expression
    'HP:0001475',  # male-limited expression
    'HP:0003743',  # genetic anticipation
    'HP:0003744',  # genetic anticipation with paternal bias
    'HP:0003745',  # sporadic
    'HP:0003829',  # incomplete penetrance
    'HP:0003831',  # age-related onset
    'HP:0025352',  # typically de novo
    'HP:0032382',  # uniparental disomy
    'HP:0032384',  # inheritance qualifier
    'HP:0034344',  # female-limited expression
    'HP:4000158',  # high penetrance
}

GTF_ATTRIBUTE_RE = re.compile(r'(\w+) "([^"]*)";')
HPO_RELEASE_RE = re.compile(r'^v(\d{4}-\d{2}-\d{2})$')


@dataclass(frozen=True, order=True)
class GeneAssociation:
    """An HPO disease-to-gene association."""

    ncbi_gene_id: str
    symbol: str


@dataclass(frozen=True, order=True)
class Locus:
    """A primary-assembly GRCh38 Ensembl gene locus."""

    ensg: str
    chrom: str
    start: int
    end: int
    symbol: str

    @property
    def location(self) -> str:
        """Return the location format used in DownloadedPanelApp."""
        return f'{self.chrom}:{self.start}-{self.end}'


@dataclass
class DiseaseAnnotation:
    """Phenotype and inheritance annotations for one OMIM disease."""

    name: str = ''
    phenotype_terms: set[str] | None = None
    inheritance_terms: set[str] | None = None

    def __post_init__(self) -> None:
        self.phenotype_terms = self.phenotype_terms or set()
        self.inheritance_terms = self.inheritance_terms or set()


@dataclass(frozen=True)
class HpoRelease:
    """The selected HPO release and its required assets."""

    tag: str
    release_date: date
    genes_to_disease_url: str
    phenotype_annotations_url: str


@dataclass(frozen=True)
class OmimSourcePaths:
    """Downloaded files required to construct OMIM panels."""

    genes_to_disease: Path
    phenotype_annotations: Path
    gene2ensembl: Path
    ensembl_gtf: Path


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=5, exp_base=2),
    retry=retry_if_exception_type(httpx.RequestError),
    reraise=True,
)
def _get_response(url: str, accept: str) -> httpx.Response:
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=60,
        headers={'Accept': accept, 'User-Agent': 'talos-omim-panel-builder'},
    )
    response.raise_for_status()
    return response


def _get_json(url: str) -> dict | list:
    response = _get_response(url, 'application/json')
    return response.json()


def select_hpo_release(releases: list[dict], target_date: date) -> HpoRelease:
    """Select the newest usable HPO release not later than ``target_date``."""
    candidates: list[HpoRelease] = []
    for release in releases:
        if release.get('draft') or release.get('prerelease'):
            continue
        match = HPO_RELEASE_RE.fullmatch(release.get('tag_name', ''))
        if not match:
            continue
        release_date = date.fromisoformat(match.group(1))
        if release_date > target_date:
            continue
        assets = {asset['name']: asset['browser_download_url'] for asset in release.get('assets', [])}
        if {'genes_to_disease.txt', 'phenotype.hpoa'} <= assets.keys():
            candidates.append(
                HpoRelease(
                    tag=release['tag_name'],
                    release_date=release_date,
                    genes_to_disease_url=assets['genes_to_disease.txt'],
                    phenotype_annotations_url=assets['phenotype.hpoa'],
                )
            )
    if not candidates:
        raise ValueError(f'No usable HPO release found on or before {target_date}')
    return max(candidates, key=lambda release: release.release_date)


def discover_hpo_release(target_date: date) -> HpoRelease:
    """Query the official HPO releases and choose the release for a build date."""
    releases = _get_json(HPO_RELEASES_URL)
    if not isinstance(releases, list):
        raise TypeError('HPO release API did not return a list')
    return select_hpo_release(releases, target_date)


def discover_ensembl_gtf() -> tuple[int, str]:
    """Return the current Ensembl release and its human GRCh38 GTF URL."""
    version = _get_response(ENSEMBL_VERSION_URL, 'text/plain').text.strip()
    if not version.isdigit():
        raise ValueError(f'Ensembl VERSION did not contain a release number: {version!r}')
    release = int(version)
    return release, ENSEMBL_GTF_TEMPLATE.format(release=release)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=5, exp_base=2),
    retry=retry_if_exception_type(httpx.RequestError),
    reraise=True,
)
def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f'{destination.name}.part')
    try:
        with httpx.stream(
            'GET',
            url,
            follow_redirects=True,
            timeout=120,
            headers={'User-Agent': 'talos-omim-panel-builder'},
        ) as response:
            response.raise_for_status()
            with partial.open('wb') as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
        if not partial.stat().st_size:
            raise ValueError(f'Downloaded an empty file from {url}')
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def download_omim_sources(target_date: date, directory: Path) -> tuple[HpoRelease, OmimSourcePaths]:
    """Download the closest HPO release and current gene lookup sources."""
    hpo_release = discover_hpo_release(target_date)
    ensembl_release, ensembl_url = discover_ensembl_gtf()
    logger.info(f'Using HPO {hpo_release.tag} and Ensembl {ensembl_release} for OMIM panels')

    paths = OmimSourcePaths(
        genes_to_disease=directory / f'genes_to_disease_{hpo_release.tag}.txt',
        phenotype_annotations=directory / f'phenotype_{hpo_release.tag}.hpoa',
        gene2ensembl=directory / 'gene2ensembl.gz',
        ensembl_gtf=directory / f'Homo_sapiens.GRCh38.{ensembl_release}.gtf.gz',
    )
    for url, path in (
        (hpo_release.genes_to_disease_url, paths.genes_to_disease),
        (hpo_release.phenotype_annotations_url, paths.phenotype_annotations),
        (NCBI_GENE2ENSEMBL_URL, paths.gene2ensembl),
        (ensembl_url, paths.ensembl_gtf),
    ):
        logger.info(f'Downloading {url}')
        _download(url, path)
    return hpo_release, paths


def _open_text(path: Path) -> TextIO:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f'Missing or empty OMIM source: {path}')
    if path.suffix == '.gz':
        return gzip.open(path, 'rt', newline='')
    return path.open(newline='')


def _require_columns(fieldnames: list[str] | None, required: set[str], path: Path) -> None:
    if missing := required - set(fieldnames or []):
        raise ValueError(f'{path} is missing columns: {", ".join(sorted(missing))}')


def parse_gene_associations(path: Path) -> dict[str, set[GeneAssociation]]:
    """Read Mendelian OMIM disease-to-gene associations from HPO."""
    associations: dict[str, set[GeneAssociation]] = defaultdict(set)
    required = {'disease_id', 'association_type', 'ncbi_gene_id', 'gene_symbol'}
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        _require_columns(reader.fieldnames, required, path)
        for row in reader:
            disease_id = row['disease_id']
            if not disease_id.startswith('OMIM:') or row['association_type'] != 'MENDELIAN':
                continue
            gene_id = row['ncbi_gene_id'].removeprefix('NCBIGene:')
            if gene_id.isdigit():
                associations[disease_id].add(GeneAssociation(gene_id, row['gene_symbol']))
    return dict(associations)


def parse_hpo_annotations(path: Path) -> tuple[dict[str, DiseaseAnnotation], str | None]:
    """Read positive phenotypes and inheritance terms for OMIM diseases."""
    annotations: dict[str, DiseaseAnnotation] = defaultdict(DiseaseAnnotation)
    required = {'database_id', 'disease_name', 'qualifier', 'hpo_id', 'aspect'}
    version = None
    with _open_text(path) as handle:
        header = None
        for line in handle:
            if line.startswith('#'):
                key, separator, value = line[1:].partition(':')
                if separator and key.strip() == 'version':
                    version = value.strip().strip('"')
                continue
            header = line.rstrip('\n').split('\t')
            break
        _require_columns(header, required, path)

        for row in csv.DictReader(handle, delimiter='\t', fieldnames=header):
            disease_id = row['database_id']
            if not disease_id.startswith('OMIM:'):
                continue
            annotation = annotations[disease_id]
            annotation.name = annotation.name or row['disease_name'].strip()
            if row['qualifier'] == 'NOT':
                continue
            if row['aspect'] == 'P':
                annotation.phenotype_terms.add(row['hpo_id'])
            elif row['aspect'] == 'I':
                annotation.inheritance_terms.add(row['hpo_id'])
    return dict(annotations), version


def normalize_moi(terms: set[str]) -> str | None:
    """Convert HPO inheritance terms to a PanelApp MOI, or reject ambiguity."""
    known_terms = set(MOI_TERM_CLASSES) | INHERITANCE_QUALIFIERS | {GENERIC_X_LINKED_TERM}
    if terms - known_terms:
        return None

    classes = {MOI_TERM_CLASSES[term] for term in terms if term in MOI_TERM_CLASSES}
    if GENERIC_X_LINKED_TERM in terms and not classes.intersection({'XLR', 'XLD'}):
        return None
    if not classes:
        return None

    imprinting = classes.intersection({'AD_PATERNALLY_IMPRINTED', 'AD_MATERNALLY_IMPRINTED'})
    if imprinting:
        if len(imprinting) != 1 or classes - imprinting - {'AD'}:
            return None
        return MOI_PATERNALLY_IMPRINTED if 'AD_PATERNALLY_IMPRINTED' in imprinting else MOI_MATERNALLY_IMPRINTED

    mapping = {
        frozenset({'AD'}): MOI_AUTOSOMAL_DOMINANT,
        frozenset({'AR'}): MOI_AUTOSOMAL_RECESSIVE,
        frozenset({'AD', 'AR'}): MOI_AUTOSOMAL_BOTH,
        frozenset({'XLR'}): MOI_X_RECESSIVE,
        frozenset({'XLD'}): MOI_X_DOMINANT,
        frozenset({'XLD', 'XLR'}): MOI_X_DOMINANT,
        frozenset({'MT'}): MOI_MITOCHONDRIAL,
    }
    return mapping.get(frozenset(classes))


def parse_ncbi_ensembl(path: Path, wanted_gene_ids: set[str]) -> dict[str, set[str]]:
    """Read human NCBI Gene-to-Ensembl mappings for the required genes."""
    mappings: dict[str, set[str]] = defaultdict(set)
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter='\t')
        header = next(reader, None)
        if not header or len(header) < 3:
            raise ValueError(f'Invalid gene2ensembl header in {path}')
        for row in reader:
            if len(row) >= 3 and row[0] == '9606' and row[1] in wanted_gene_ids and row[2].startswith('ENSG'):
                mappings[row[1]].add(row[2])
    return dict(mappings)


def parse_ensembl_gtf(
    path: Path,
    wanted_ensgs: set[str],
    wanted_symbols: set[str],
) -> tuple[dict[str, set[Locus]], dict[str, set[Locus]]]:
    """Read required gene loci from the primary GRCh38 assembly."""
    by_ensg: dict[str, set[Locus]] = defaultdict(set)
    by_symbol: dict[str, set[Locus]] = defaultdict(set)
    with _open_text(path) as handle:
        for line in handle:
            if line.startswith('#'):
                continue
            fields = line.rstrip('\n').split('\t')
            if len(fields) != 9 or fields[2] != 'gene':
                continue
            chrom = 'M' if fields[0] == 'MT' else fields[0]
            if chrom not in PRIMARY_CHROMS:
                continue
            attributes = dict(GTF_ATTRIBUTE_RE.findall(fields[8]))
            ensg = attributes.get('gene_id', '')
            symbol = attributes.get('gene_name', '')
            if ensg not in wanted_ensgs and symbol not in wanted_symbols:
                continue
            locus = Locus(ensg, chrom, int(fields[3]), int(fields[4]), symbol)
            if ensg in wanted_ensgs:
                by_ensg[ensg].add(locus)
            if symbol in wanted_symbols:
                by_symbol[symbol].add(locus)
    return dict(by_ensg), dict(by_symbol)


def choose_locus(
    association: GeneAssociation,
    ncbi_to_ensg: dict[str, set[str]],
    loci_by_ensg: dict[str, set[Locus]],
    loci_by_symbol: dict[str, set[Locus]],
) -> Locus | None:
    """Choose one unambiguous locus, preferring NCBI mappings over symbols."""
    direct = {
        locus for ensg in ncbi_to_ensg.get(association.ncbi_gene_id, set()) for locus in loci_by_ensg.get(ensg, set())
    }
    if len(direct) == 1:
        return next(iter(direct))
    if len(direct) > 1:
        x_loci = {locus for locus in direct if locus.chrom == 'X'}
        y_loci = {locus for locus in direct if locus.chrom == 'Y'}
        if len(x_loci) == 1 and y_loci and len(x_loci) + len(y_loci) == len(direct):
            return next(iter(x_loci))
        return None

    symbol_loci = loci_by_symbol.get(association.symbol, set())
    return next(iter(symbol_loci)) if len(symbol_loci) == 1 else None


def panel_id_for_disease(disease_id: str) -> int:
    """Create a stable synthetic panel ID from an OMIM disease ID."""
    prefix, separator, identifier = disease_id.partition(':')
    if prefix != 'OMIM' or not separator or not identifier.isdigit():
        raise ValueError(f'Invalid OMIM disease identifier: {disease_id}')
    return PANEL_ID_OFFSET + int(identifier)


def build_omim_panel(
    paths: OmimSourcePaths,
    hpo_release: HpoRelease,
    build_date: date,
    existing_panel_ids: set[int] | None = None,
) -> DownloadedPanelApp:
    """Construct a validated DownloadedPanelApp supplement containing OMIM panels."""
    disease_genes = parse_gene_associations(paths.genes_to_disease)
    annotations, annotation_version = parse_hpo_annotations(paths.phenotype_annotations)
    associations = {item for items in disease_genes.values() for item in items}
    wanted_gene_ids = {item.ncbi_gene_id for item in associations}
    wanted_symbols = {item.symbol for item in associations if item.symbol != '-'}
    ncbi_to_ensg = parse_ncbi_ensembl(paths.gene2ensembl, wanted_gene_ids)
    wanted_ensgs = {ensg for values in ncbi_to_ensg.values() for ensg in values}
    loci_by_ensg, loci_by_symbol = parse_ensembl_gtf(paths.ensembl_gtf, wanted_ensgs, wanted_symbols)

    supplement = DownloadedPanelApp(date=build_date.isoformat())
    existing_panel_ids = existing_panel_ids or set()
    for disease_id in sorted(disease_genes, key=lambda value: int(value.split(':', 1)[1])):
        annotation = annotations.get(disease_id, DiseaseAnnotation())
        moi = normalize_moi(annotation.inheritance_terms)
        if not annotation.phenotype_terms or moi is None:
            continue

        panel_id = panel_id_for_disease(disease_id)
        if panel_id in existing_panel_ids:
            raise ValueError(f'OMIM panel ID {panel_id} collides with a PanelApp panel')

        resolved_genes = 0
        for association in sorted(disease_genes[disease_id]):
            locus = choose_locus(association, ncbi_to_ensg, loci_by_ensg, loci_by_symbol)
            if locus is None:
                continue
            panel_detail = DownloadedPanelAppPanel(
                moi=moi,
                date=ASSOCIATION_DATE,
                confidence=OMIM_CONFIDENCE,
            )
            if existing_gene := supplement.genes.get(locus.ensg):
                existing_gene.panels[panel_id] = panel_detail
            else:
                supplement.genes[locus.ensg] = DownloadedPanelAppGene(
                    symbol=locus.symbol or association.symbol,
                    chrom=locus.chrom,
                    location=locus.location,
                    ensg=locus.ensg,
                    panels={panel_id: panel_detail},
                )
            resolved_genes += 1

        if not resolved_genes:
            continue
        supplement.versions.append(
            PanelShort(
                id=panel_id,
                name=f'{disease_id} {annotation.name}'.strip(),
                version=f'HPOA-{annotation_version or hpo_release.release_date.isoformat()}',
            )
        )
        supplement.hpos[panel_id] = [HpoTerm(id=hpo_id, label='') for hpo_id in sorted(annotation.phenotype_terms)]
    return DownloadedPanelApp.model_validate(supplement.model_dump())


def merge_omim_panel(panelapp: DownloadedPanelApp, omim: DownloadedPanelApp) -> DownloadedPanelApp:
    """Merge an OMIM supplement while preserving PanelApp gene metadata."""
    merged = panelapp.model_copy(deep=True)
    panelapp_ids = {panel.id for panel in merged.versions}
    omim_ids = {panel.id for panel in omim.versions}
    if collisions := panelapp_ids & omim_ids:
        raise ValueError(f'OMIM panel IDs collide with PanelApp: {sorted(collisions)}')

    merged.versions.extend(omim.versions)
    merged.hpos.update(omim.hpos)
    for ensg, omim_gene in omim.genes.items():
        if panelapp_gene := merged.genes.get(ensg):
            panelapp_gene.panels.update(omim_gene.panels)
        else:
            merged.genes[ensg] = omim_gene
    return DownloadedPanelApp.model_validate(merged.model_dump())


def add_omim_to_panelapp_file(panelapp_path: str | Path, target_date: date | None = None) -> tuple[Path, Path]:
    """Merge current OMIM panels in place and preserve raw PanelApp as ``.bk``."""
    panelapp_path = Path(panelapp_path)
    backup_path = panelapp_path.with_name(f'{panelapp_path.name}.bk')
    if backup_path.exists():
        raise FileExistsError(f'Refusing to overwrite existing PanelApp backup: {backup_path}')
    with panelapp_path.open() as handle:
        panelapp = DownloadedPanelApp.model_validate(json.load(handle))

    target_date = target_date or datetime.now(tz=UTC).date()
    with tempfile.TemporaryDirectory(prefix='talos-omim-') as temporary_directory:
        hpo_release, paths = download_omim_sources(target_date, Path(temporary_directory))
        omim = build_omim_panel(
            paths,
            hpo_release,
            target_date,
            {panel.id for panel in panelapp.versions},
        )
    merged = merge_omim_panel(panelapp, omim)
    logger.info(f'Adding {len(omim.versions)} OMIM panels and {len(omim.genes)} OMIM genes')

    combined_part = panelapp_path.with_name(f'{panelapp_path.name}.part')
    try:
        combined_part.write_text(merged.model_dump_json(indent=4))
        panelapp_path.replace(backup_path)
        try:
            combined_part.replace(panelapp_path)
        except Exception:
            backup_path.replace(panelapp_path)
            raise
    finally:
        combined_part.unlink(missing_ok=True)
    return panelapp_path, backup_path
