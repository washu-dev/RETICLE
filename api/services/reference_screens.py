"""Real, verified BioGRID ORCS screens used to seed the offline / no-database path.

The offline branch used to hand out fabricated PMIDs and "ORCS-####" ids, so the
PubMed and BioGRID link-outs landed on unrelated (or non-existent) pages. Every
entry here was verified on 2026-07-30 against orcs.thebiogrid.org and
pubmed.ncbi.nlm.nih.gov, so:

  - screen_id      is a real BioGRID ORCS screen  -> /Screen/{screen_id} resolves
  - pmid           is that screen's real paper     -> /pubmed/{pmid} resolves
  - citation/title match the pmid

Keyed lookups (BY_ID) let screen_detail return the correct detail for whichever
matched screen the user clicked. The identity fields live here once; demo-only
overlap stats (rho, shared genes) stay with the caller.
"""

REFERENCE_SCREENS: list[dict] = [
    {
        "screen_id": "833", "pmid": "30971826", "author": "Behan FM (2019)",
        "title": "Prioritization of cancer therapeutic targets using CRISPR-Cas9 screens",
        "journal": "Nature", "organism": "Homo sapiens",
        "cell_line": "KYSE-510", "cell_type": "Oesophageal carcinoma",
        "modality": "KO", "phenotype": "cell fitness",
    },
    {
        "screen_id": "1022", "pmid": "30995489", "author": "MacLeod G (2019)",
        "title": ("Genome-Wide CRISPR-Cas9 Screens Expose Genetic Vulnerabilities and "
                  "Mechanisms of Temozolomide Sensitivity in Glioblastoma Stem Cells"),
        "journal": "Cell Reports", "organism": "Homo sapiens",
        "cell_line": "G523NS-Cas9", "cell_type": "Glioblastoma stem cells",
        "modality": "KO", "phenotype": "temozolomide sensitivity",
    },
    {
        "screen_id": "1396", "pmid": "33189395", "author": "Zhao Y (2020)",
        "title": ("Applying genome-wide CRISPR to identify known and novel genes and "
                  "pathways that modulate formaldehyde toxicity"),
        "journal": "Chemosphere", "organism": "Homo sapiens",
        "cell_line": "K-562", "cell_type": "Chronic myelogenous leukemia",
        "modality": "KO", "phenotype": "formaldehyde toxicity",
    },
    {
        "screen_id": "101", "pmid": "28145866", "author": "Krall EB (2017)",
        "title": "KEAP1 loss modulates sensitivity to kinase targeted therapy in lung cancer",
        "journal": "eLife", "organism": "Homo sapiens",
        "cell_line": "NCI-H1299", "cell_type": "Non-small-cell lung cancer",
        "modality": "KO", "phenotype": "kinase-inhibitor sensitivity",
    },
    {
        "screen_id": "1172", "pmid": "31019072", "author": "Li Y (2019)",
        "title": "Genome-wide CRISPR screen for Zika virus resistance in human neural cells",
        "journal": "PNAS", "organism": "Homo sapiens",
        "cell_line": "iPSC-derived neural progenitor", "cell_type": "Neural progenitor",
        "modality": "KO", "phenotype": "Zika virus resistance",
    },
    {
        "screen_id": "2400", "pmid": "32028983", "author": "Lau MT (2020)",
        "title": "Systematic functional identification of cancer multi-drug resistance genes",
        "journal": "Genome Biology", "organism": "Homo sapiens",
        "cell_line": "HAP-1", "cell_type": "Near-haploid",
        "modality": "KO", "phenotype": "multi-drug resistance",
    },
]

BY_ID: dict[str, dict] = {s["screen_id"]: s for s in REFERENCE_SCREENS}


def citation_for(entry: dict) -> str:
    """A formatted, link-consistent citation string, e.g. 'Behan FM (2019) · Nature'."""
    author = entry.get("author", "")
    journal = entry.get("journal", "")
    return " · ".join(p for p in (author, journal) if p)
