"""
drug_mechanism.py — map a BioGRID drug condition name -> mechanism-of-action bucket.
==================================================================================
This is the operationalised "compound-semantic slot": a drug is placed by its TARGET/
MECHANISM (the drug's designed pharmacology, established before any screen), NEVER by
which genes scored — so it stays inside the anti-circularity line. v1 uses this frozen
hand-curated head map (~71% of drug screens; validated to recover screen power in
test_mechanism_power.py). The scalable version LLM-classifies the full tail and cross-
checks with chemical structure (SMILES fingerprint) + Reactome (target -> pathway).

Unmapped drugs return None = "uncharted context" — honestly excluded, never faked.
"""

# (mechanism bucket, [lowercased substrings]). First match wins.
RULES = [
    ("DDR·PARP",        ["olaparib", "talazoparib", "niraparib", "rucaparib", "thioparib", "cpd-391", "cpd‐391", "phthalazin"]),
    ("DDR·ATR/ATM/CHK1", ["azd6738", "berzosertib", "ve822", "ve-822", "prexasertib", "rabusertib", "ly2603618", "m3541", "atm inhibitor", "atr inhibitor", "chk1", "ceralasertib"]),
    ("DDR·genotoxic",   ["cisplatin", "oxaliplatin", "carboplatin", "etoposide", "camptothecin", "irinotecan", "topotecan", "doxorubicin", "gemcitabine", "hydroxyurea", "fluorouracil", "temozolomide", "mitomycin", "methanesulfonate", "mms", "bleomycin", "cytarabine", "methotrexate", "formaldehyde", "illudin", "pyridostatin"]),
    ("Microtubule",     ["paclitaxel", "taxol", "docetaxel", "colchicine", "vincristine", "nocodazole", "vinblastine"]),
    ("PLK",             ["bi-2536", "bi2536", "volasertib"]),
    ("CDK",             ["dinaciclib", "palbociclib", "ribociclib", "abemaciclib", "ro-3306", "thz-1", "thz1", "cdk9i", "azd5576", "cdk7", "seliciclib", "cdk"]),
    ("MAPK",            ["vemurafenib", "dabrafenib", "plx-4720", "plx4720", "trametinib", "selumetinib", "cobimetinib", "sorafenib", "shp099", "erlotinib", "gefitinib", "osimertinib", "binimetinib"]),
    ("BET/BRD4",        ["jq1", "abbv-744", "abbv744", "i-bet", "ibet", "bet inhibitor"]),
    ("BCL2/apoptosis",  ["venetoclax", "navitoclax", "abt-737", "abt-199", "abt737", "s63845"]),
    ("XPO1",            ["selinexor", "kpt-"]),
    ("Proteasome/UPS",  ["bortezomib", "carfilzomib", "ixazomib", "mg132", "mg-132", "tak-243", "tak243", "mln4924"]),
    ("Cereblon/IMiD",   ["lenalidomide", "pomalidomide", "avadomide", "cc-122", "cc122", "thalidomide"]),
    ("HDAC",            ["panobinostat", "vorinostat", "saha", "romidepsin", "entinostat"]),
    ("ER-stress/UPR",   ["tunicamycin", "thapsigargin", "brefeldin"]),
    ("Mito/OXPHOS",     ["antimycin", "oligomycin", "cccp", "rotenone", "oar", "dichloroacetic", "dca", "fccp"]),
    ("Ferroptosis",     ["rsl3", "ml-210", "ml210", "erastin", "gpx4"]),
    ("Spliceosome",     ["pladienolide", "pladb", "e7107", "h3b"]),
    ("Autophagy",       ["hydroxychloroquine", "chloroquine", "bafilomycin"]),
    ("Oxidative",       ["h2o2", "hydrogen peroxide", "peroxide", "tbhp", "menadione", "paraquat"]),
    ("KEAP1/NRF2",      ["ki-696", "ki696"]),
    ("mTOR/PI3K",       ["rapamycin", "torin", "everolimus", "temsirolimus", "pi3k", "wortmannin"]),
    ("Antiviral",       ["remdesivir", "molnupiravir"]),
]


def bucket(name):
    """Drug condition name -> mechanism bucket, or None if unrecognised (uncharted)."""
    if not name:
        return None
    n = name.lower()
    for buck, keys in RULES:
        if any(k in n for k in keys):
            return buck
    return None
