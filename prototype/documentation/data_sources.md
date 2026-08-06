# RETICLE Gene Explorer — where the data comes from

> Every gene search on this site fires **three requests**, each hitting a different set of
> sources. This document says what **STRING / PubMed / NCBI / GO / BioGRID** each contribute,
> which part of the interface they appear in, and which code produces them.

Code: backend `web/app.py` + `script/external_sources.py`; frontend `web/index.html`.

---

## The summary table

| Source | What it provides | Backend entry point | What you see in the UI |
|---|---|---|---|
| **BioGRID** (local DB) | The entire **quantitative report**: the fitness / stress / reporter axes, percentile distribution, hits, cell line, context, verdict | `/api/gene` → `gene_payload()` | Every chart below the gene name (bipolar axis, histogram, "where it matters most", the flip notice) |
| **PubMed** (via NCBI E-utilities) | (1) paper **count** → darkness; (2) paper **abstracts** → RAG evidence | `/api/context` (count)<br>`/api/interpret` (abstracts) | "N papers" on the darkness card; the **PMID citation links** under the AI reading |
| **NCBI** (gene annotation, via MyGene.info) | Gene name + **RefSeq functional summary** | `/api/context` → `gene_annotation()` | The prose in the "Known to science" section |
| **GO** (Gene Ontology, via MyGene.info) | **Number** of GO annotations → the other half of darkness | `/api/context` → `gene_annotation()` | "N GO terms" on the darkness card, and the darkness score itself |
| **STRING** | Known **functional partners** | `/api/context` + `/api/interpret` | The clickable partner chips in "Known to science"; also fed to the model |
| **WashU gpt-4o** (not a source — a synthesiser) | Combines everything above into one reading | `/api/interpret` → `interpret()` | The "AI reading" paragraph |

> Two common misunderstandings worth clearing up:
> 1. **PubMed IS one of NCBI's databases.** The site reaches PubMed through NCBI E-utilities
>    (`esearch` / `efetch`), so "PubMed" and "NCBI" are the same infrastructure.
> 2. The "NCBI gene annotation" row (name + RefSeq summary) and the GO count are **actually
>    fetched through MyGene.info**, which aggregates NCBI/Entrez RefSeq and GO — not by calling
>    NCBI E-utilities directly. The **origin** of the data is NCBI/GO; the **channel** is MyGene.

---

## What the three requests hit, for one gene search

```
user searches "C1orf109"
│
├─ 1. GET /api/gene?symbol=C1orf109          ── BioGRID only (local, instant)
│      gene_payload(): reads harmonized_scores + screen_metadata + screen_metadata_curated
│      → the fitness / stress / reporter blocks + verdict
│      → renders: gene name, bipolar axis, histogram, context column, flip notice
│
├─ 2. GET /api/context?symbol=C1orf109       ── MyGene + NCBI(PubMed) + STRING (cached)
│      ex.enrich():
│        · gene_annotation()  → MyGene: name + RefSeq summary + GO count
│        · darkness()         → pubmed_count() [NCBI esearch] + GO count → a 0-10 score
│        · string_partners()  → STRING: known partners
│      → renders: the "Known to science + darkness" band
│
└─ 3. POST /api/interpret                     ── reuses the enrich above + pulls PubMed abstracts
       interpret():                              + gpt-4o
         · ex.enrich()                         → darkness / summary / partners (cache hit; no
                                                 second network call)
         · pubmed_abstracts(pubmed_pmids())    → NCBI efetch: the top-5 relevant abstracts
                                                 (this is the RAG retrieval step)
         · WashU gpt-4o                        → synthesises BioGRID signal + darkness + STRING
                                                 + abstracts
       → renders: the "AI reading" text + PMID citation links
```

---

## Source by source

### 1. BioGRID — the site's quantitative core
- **What it is**: the local SQLite your own pipeline produced
  (`processed_data/reticle_master.db`): `harmonized_scores` (28.2M rows) + `screen_metadata` +
  `screen_metadata_curated` (which carries `assay_domain`).
- **Where it is used**: `gene_payload()` behind `/api/gene`. It is the **only** offline,
  instant source.
- **In the UI**: gene name, verdict, the fitness and stress blocks (bipolar axis + four stat
  cards + histogram + "where it matters most"), the reporter count, the flip notice — **all of
  it comes from BioGRID**.
- **Needs no network and no key.**

### 2. PubMed (via NCBI E-utilities) — two distinct uses
- **Paper count**: `pubmed_count()` uses `esearch` (`{gene}[gene] AND human[orgn]`) for the
  total. This is the dominant term in the **darkness score**, and the "N papers" on the card.
- **Abstracts**: `pubmed_abstracts(pubmed_pmids())` uses `esearch` (top-5 PMIDs by relevance)
  then `efetch` (the abstracts). These are fed to gpt-4o as **RAG evidence**, and the AI reading
  lists those PMIDs as its citations.
- **Key**: `NCBI_API_KEY` in `.env` (already set) raises the rate limit to 10 requests/second
  from 3.

### 3. NCBI gene annotation (via MyGene.info)
- **What it is**: `gene_annotation()` calls MyGene.info for `entrezgene` + `name` + the
  **RefSeq summary** + GO terms.
- **In the UI**: the functional description in "Known to science" (a dark gene with no summary
  shows "Poorly characterized...").
- **No key needed.**

### 4. GO (Gene Ontology, via MyGene.info)
- **What it is**: the GO count (BP+MF+CC) = `go_total`, from the same MyGene call as above.
- **Where it is used**: the **other half of the darkness score** (fewer annotations = darker),
  and the "N GO terms" on the card.
- **No key needed.**

### 5. STRING — known functional partners
- **What it is**: `string_partners()` calls the STRING API for the top interaction/functional
  partners.
- **In the UI**: the row of clickable partner chips in "Known to science" (clicking one explores
  that gene).
- **Also fed to the model**: the interpret prompt carries a "KNOWN PARTNERS (STRING)" section, so
  the model can judge whether a dark gene behaves consistently with known partners — i.e.
  whether it is a de-orphaning candidate.
- **No key needed.**

### 6. WashU gpt-4o — the synthesiser, not a source
- Combines the BioGRID signal + darkness + STRING + PubMed abstracts into one reading, under
  instructions to **cite PMIDs** and invent nothing.
- Goes through `script/llm_client.py` (the WashU gateway), which **requires the WashU VPN**.

---

## Which sources feed the darkness score

darkness = `10 × (0.6·dark_pub + 0.4·dark_go)`
- `dark_pub` ← the **PubMed paper count** (NCBI esearch)
- `dark_go`  ← the **number of GO annotations** (MyGene/GO)

So **darkness combines exactly two sources, PubMed and GO**. BioGRID and STRING do not enter the
darkness calculation at all.

---

## Caching and offline behaviour
- Every external result (NCBI / MyGene / STRING) is cached in
  `processed_data/external_cache.db` with a 30-day TTL, so the second lookup of the same gene is
  **instant and makes no network call**.
- **Offline or without the VPN**: `/api/gene` (BioGRID) works as normal; `/api/context` depends
  on the public internet (NCBI / MyGene / STRING are public and usually reachable);
  `/api/interpret` needs the WashU VPN for gpt-4o, and otherwise fails gracefully with a message
  telling you to connect.
- All external sources **fail soft**: a source that is down returns empty/None rather than
  taking the page down with it.
