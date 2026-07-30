"""Screen-vs-screen similarity (ported from the standalone prototype).

Given a query CRISPR fitness screen, return other human genome-wide fitness screens whose
gene-level profile resembles it.

Served entirely from two precomputed RDS tables — reticle.screen_similarity (~789k directed pairs)
and reticle.screen_sim_meta (962 screens) — built offline by
prototype/script/migrate_screen_similarity.py. Nothing is computed per request: the prototype
originally loaded a 57 MB .npz and ran an SVD on first call, which made this the one feature that
could not work on a cloud deploy at all.

Three deliberate choices in the precomputed definition, each measured on this matrix:
  * PLAIN pairwise-complete Pearson on PC1-REMOVED values. PC1 is the pan-essentiality axis: it
    carries ~44.5% of the variance and its gene loading correlates ~0.998 with each gene's mean
    percentile, so leaving it in makes ANY two human fitness screens correlate ~0.35 before any
    biology. An earlier version instead ranked by a "weighted" Pearson with w = |a|*|b|, which is
    selection on the outcome — it inflated r by ~0.17 (0.695 -> 0.869 on a real pair) by
    up-weighting exactly the pan-essential genes every fitness screen shares.
  * min_overlap 2,000 co-measured genes. 200 shared genes out of ~19k is a noise-dominated estimate.
  * Z AGAINST THE QUERY'S OWN BACKGROUND, computed here at request time. A raw r is unreadable on
    its own; z = (r - mean_r) / sd_r over the whole comparable pool answers the question the user
    actually has — "is this MORE alike than usual?"

KNOWN, UNFIXED — the batch/study effect dominates and is not removed by any of the above: for a
Behan-2019 query all top-50 hits were that same publication, and after excluding it the next 9/10
were a single other publication. Same study = same library, protocol, batch and analysis, which is a
real technical similarity. `same_study` is therefore returned per row and `exclude_same_study` is
offered, so the caller can see and control the confound rather than mistake it for biology. Even the
best cross-study match usually sits only ~1.2 sd above background.
"""

import logging
from typing import Any

import numpy as np

from services.db_service import db_fetchall

logger = logging.getLogger(__name__)

# Not exposed as a query parameter: the precomputed table was already filtered at this threshold,
# so raising it here would silently under-report and lowering it cannot recover dropped pairs.
MIN_OVERLAP = 2000


async def get_screen_similar(
    screen_id: str,
    limit: int = 50,
    offset: int = 0,
    exclude_same_study: bool = False,
) -> dict[str, Any] | None:
    """Screens whose gene-level fitness profile resembles the query's.

    Returns None when the query screen is not in the comparable pool (human, fitness, genome-wide),
    which the router turns into a 404.
    """
    sid = str(screen_id).strip()

    qm = db_fetchall(
        "SELECT screen_id, author, cell_line, pmid, n_genes "
        "FROM screen_sim_meta WHERE screen_id = ?",
        (sid,),
    )
    if not qm:
        return None
    qrow = qm[0]
    qpmid = str(qrow["pmid"] or "")

    raw = db_fetchall(
        """SELECT s.screen_b sb, s.r, s.overlap, m.author, m.cell_line, m.pmid, m.n_genes
           FROM screen_similarity s JOIN screen_sim_meta m ON m.screen_id = s.screen_b
           WHERE s.screen_a = ? AND s.overlap >= ?""",
        (sid, MIN_OVERLAP),
    )

    rows: list[dict[str, Any]] = []
    for x in raw:
        pm = str(x["pmid"] or "")
        rows.append(
            {
                "screen_id": x["sb"],
                "r": round(float(x["r"]), 3),
                "overlap": int(x["overlap"]),
                "same_study": bool(pm and pm == qpmid),
                "author": str(x["author"] or "—"),
                "cell_line": str(x["cell_line"] or "—"),
                "pmid": pm,
                "n_genes": int(x["n_genes"]) if x["n_genes"] is not None else None,
            }
        )

    # Background = this query's correlation against the whole comparable pool. Computed BEFORE the
    # same-study filter on purpose, so the toggle changes which rows are shown but never moves the
    # yardstick they are measured against.
    if rows:
        allr = np.array([x["r"] for x in rows], dtype=np.float64)
        mu, sd = float(allr.mean()), float(allr.std())
        # Not `x`: that name is already bound to a _Row by the loop above, and rebinding it to a
        # plain dict here is a type error.
        for row in rows:
            row["z"] = round((row["r"] - mu) / sd, 2) if sd > 0 else 0.0
    else:
        mu = sd = 0.0

    n_same = sum(1 for x in rows if x["same_study"])
    if exclude_same_study:
        rows = [x for x in rows if not x["same_study"]]
    # Ranked by raw r. z is a strictly monotonic transform of r here (one shared mu/sd), so this is
    # also z-descending — the two can never disagree.
    rows.sort(key=lambda x: -x["r"])

    offset = max(0, int(offset))
    limit = max(1, int(limit))
    return {
        "query": {
            "screen_id": sid,
            "author": str(qrow["author"] or "—"),
            "cell_line": str(qrow["cell_line"] or "—"),
            "pmid": qpmid,
            "n_genes": int(qrow["n_genes"]) if qrow["n_genes"] is not None else None,
        },
        "n_pool": len(raw) + 1,
        "n_total": len(rows),
        "offset": offset,
        "background": {"mean_r": round(mu, 3), "sd_r": round(sd, 3)},
        "n_same_study": n_same,
        "exclude_same_study": bool(exclude_same_study),
        "results": rows[offset : offset + limit],
    }
