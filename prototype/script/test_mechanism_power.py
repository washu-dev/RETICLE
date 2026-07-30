"""
test_mechanism_power.py — proof: does grouping drugs by MECHANISM (not name) recover power?
Hand-curated drug->mechanism map (me acting as the LLM once, frozen). No API, no network.
"""
import sqlite3, re
from collections import defaultdict, Counter

DB = "processed_data/reticle_master.db"

# drug (substring, lowercased) -> mechanism bucket. Ordered: first match wins.
RULES = [
    ("DDR · PARP inhibitor",      ["olaparib","talazoparib","niraparib","rucaparib","thioparib","cpd-391","cpd‐391","phthalazin"]),
    ("DDR · ATR/ATM/CHK1 kinase", ["azd6738","berzosertib","ve822","ve-822","prexasertib","rabusertib","ly2603618","m3541","atm inhibitor","atr inhibitor","chk1"]),
    ("DDR · genotoxic chemo",     ["cisplatin","oxaliplatin","carboplatin","etoposide","camptothecin","irinotecan","topotecan","doxorubicin","gemcitabine","hydroxyurea","fluorouracil","temozolomide","mitomycin","methanesulfonate","mms","bleomycin","cytarabine","methotrexate","formaldehyde","illudin","pyridostatin"]),
    ("Microtubule / mitotic",     ["paclitaxel","taxol","docetaxel","colchicine","vincristine","nocodazole"]),
    ("PLK inhibitor",             ["bi-2536","bi2536","volasertib"]),
    ("CDK inhibitor",             ["dinaciclib","palbociclib","ribociclib","abemaciclib","ro-3306","thz-1","thz1","cdk9i","azd5576","cdk7","seliciclib"]),
    ("MAPK pathway (RAF/MEK/EGFR/SHP2)", ["vemurafenib","dabrafenib","plx-4720","plx4720","trametinib","selumetinib","cobimetinib","sorafenib","shp099","erlotinib","gefitinib","osimertinib"]),
    ("BET / BRD4",                ["jq1","abbv-744","abbv744","i-bet","ibet","bet inhibitor"]),
    ("BCL2 / apoptosis",          ["venetoclax","navitoclax","abt-737","abt-199","abt737","s63845"]),
    ("Nuclear export (XPO1)",     ["selinexor","kpt-"]),
    ("Proteasome / E1 (UPS)",     ["bortezomib","carfilzomib","ixazomib","mg132","mg-132","tak-243","tak243","mln4924"]),
    ("Cereblon / IMiD",           ["lenalidomide","pomalidomide","avadomide","cc-122","cc122","thalidomide"]),
    ("HDAC inhibitor",            ["panobinostat","vorinostat","saha","romidepsin","entinostat"]),
    ("ER stress / UPR",           ["tunicamycin","thapsigargin","brefeldin"]),
    ("Mitochondria / OXPHOS",     ["antimycin","oligomycin","cccp","rotenone","oar","dichloroacetic","dca","fccp"]),
    ("Ferroptosis (GPX4)",        ["rsl3","ml-210","ml210","erastin","gpx4"]),
    ("Spliceosome (SF3B)",        ["pladienolide","pladb","e7107","h3b"]),
    ("Autophagy / lysosome",      ["hydroxychloroquine","chloroquine","bafilomycin"]),
    ("Oxidative stress",          ["h2o2","hydrogen peroxide","peroxide","tbhp","menadione","paraquat"]),
    ("KEAP1 / NRF2",              ["ki-696","ki696"]),
    ("mTOR / PI3K",               ["rapamycin","torin","everolimus","temsirolimus","pi3k","wortmannin"]),
    ("Antiviral",                 ["remdesivir","molnupiravir"]),
]

def bucket(name):
    n = name.lower()
    for buck, keys in RULES:
        if any(k in n for k in keys):
            return buck
    return None   # unmapped -> uncharted, honestly excluded

con = sqlite3.connect(DB)
drug_screens = con.execute(
    "SELECT screen_id, condition_name FROM screen_metadata_curated "
    "WHERE condition_class='drug' AND condition_name IS NOT NULL").fetchall()

by_drug = defaultdict(list)          # drug name -> [screen_id]
by_mech = defaultdict(list)          # mechanism -> [screen_id]
unmapped = []
for sid, name in drug_screens:
    by_drug[name].append(sid)
    b = bucket(name)
    (by_mech[b] if b else unmapped).append((sid, name))
    if b:
        by_mech[b]  # ensure
# rebuild by_mech as name-independent screen lists
mech_screens = defaultdict(list)
for sid, name in drug_screens:
    b = bucket(name)
    if b:
        mech_screens[b].append(sid)

n_total = len(drug_screens)
n_mapped = sum(len(v) for v in mech_screens.values())
print(f"drug screens: {n_total} | mapped to a mechanism: {n_mapped} ({100*n_mapped/n_total:.0f}%) | "
      f"unmapped (uncharted): {n_total-n_mapped}")
print(f"distinct drugs: {len(by_drug)} → distinct mechanism buckets: {len(mech_screens)}\n")

print(f"{'MECHANISM BUCKET':34} {'screens':>8}  {'#drugs pooled':>13}")
print("-"*60)
for b, sids in sorted(mech_screens.items(), key=lambda x:-len(x[1])):
    ndrugs = len({name for s,name in drug_screens if bucket(name)==b})
    print(f"{b:34} {len(sids):>8}  {ndrugs:>13}")

# ---- POWER CONTRAST: a within-context edge needs a context with >= K screens ----
def frac_in_context_ge(contexts, K):
    tot = sum(len(v) for v in contexts.values())
    good = sum(len(v) for v in contexts.values() if len(v) >= K)
    return good, tot
print("\n=== POWER: fraction of drug screens living in a context with >= K screens ===")
for K in (5, 10, 20):
    gd, td = frac_in_context_ge(by_drug, K)
    gm, tm = frac_in_context_ge(mech_screens, K)
    print(f"  K>={K:>2}:  by drug-name {gd:>4}/{td} ({100*gd/td:>3.0f}%)   |   by mechanism {gm:>4}/{tm} ({100*gm/tm:>3.0f}%)")

med_drug = sorted(len(v) for v in by_drug.values())[len(by_drug)//2]
med_mech = sorted(len(v) for v in mech_screens.values())[len(mech_screens)//2]
print(f"\n  median screens per context:  by drug-name = {med_drug}   |   by mechanism = {med_mech}")

# ---- flagship: gene-level power in the biggest bucket ----
big = max(mech_screens, key=lambda b: len(mech_screens[b]))
sids = mech_screens[big]
ph = ",".join("?"*len(sids))
gene_n = Counter()
for g, in con.execute(f"SELECT GENE_SYMBOL FROM harmonized_scores WHERE SCREEN_ID IN ({ph})", sids):
    gene_n[g]+=1
half = len(sids)//2
elig = sum(1 for g,c in gene_n.items() if c>=half)
print(f"\n=== flagship bucket '{big}' ({len(sids)} screens) ===")
print(f"  genes measured in >= half ({half}) of its screens: {elig:,}")
print(f"  → any gene-pair among those {elig:,} genes shares >= {half} observations = a real, powered correlation")
print(f"    (vs by drug-name: 62% of drugs have 1 screen → 0 shared observations → no edge computable)")
con.close()
