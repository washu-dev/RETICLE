"""A small, heuristic reference set of mouse core-essential genes + phenotype helpers.

Used ONLY as a QA gate on score harmonisation (do known-essential genes land at the
strong-phenotype tail of a fitness screen?), never to define relatedness. It is a
deliberately conservative, unambiguous set — ribosomal proteins, the proteasome, RNA
Pol II, and a handful of textbook pan-essential genes — not a full CEG list.
"""
from __future__ import annotations

# Prefixes for large, reliably essential gene families (mouse Title-case symbols).
_ESSENTIAL_PREFIXES = ("Rpl", "Rps", "Mrpl", "Mrps", "Psma", "Psmb", "Psmc", "Psmd",
                       "Eif3", "Polr1", "Polr2", "Polr3", "Nup")

# Explicit textbook pan-essential genes (replication, transcription, splicing, cell cycle).
_ESSENTIAL_GENES = {
    "Pcna", "Cdk1", "Cdk7", "Cdk9", "Ccnh", "Rrm1", "Rrm2", "Rpa1", "Rpa2", "Rpa3",
    "Prpf8", "Prpf19", "Snrnp200", "Snrpd1", "Snrpd2", "Snrpd3", "Sf3b1", "Sf3b2",
    "Eftud2", "Ran", "Rangap1", "Ranbp2", "Ncbp1", "Cct2", "Cct3", "Cct4", "Cct5",
    "Tcp1", "Vcp", "Hspa9", "Nars", "Kars", "Dars", "Gars", "Ppa1", "Atp5f1a", "Atp5f1b",
    "Uba1", "Ube2l3", "Naa10", "Copb1", "Copb2", "Copa", "Sec13", "Nup93",
}


def is_core_essential(symbol: str) -> bool:
    if not symbol:
        return False
    if symbol in _ESSENTIAL_GENES:
        return True
    return any(symbol.startswith(p) and symbol[len(p):len(p) + 1].isdigit()
               for p in _ESSENTIAL_PREFIXES)


# Phenotypes for which core-essential depletion is biologically expected.
_FITNESS_KEYWORDS = ("proliferation", "viability", "cell cycle", "tumorigenic",
                     "fitness", "growth", "survival", "essential", "dropout", "lethal")


def is_fitness_phenotype(phenotype: str) -> bool:
    p = (phenotype or "").lower()
    return any(k in p for k in _FITNESS_KEYWORDS)
