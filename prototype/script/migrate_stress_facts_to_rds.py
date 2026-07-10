"""
migrate_stress_facts_to_rds.py — push the derived `stress_facts` table (and its
`stress_consensus` view) into the RDS `reticle` schema, reusing the proven
COPY / index helpers from migrate_to_rds.py.  Only touches the `reticle` schema.

    python3 script/migrate_stress_facts_to_rds.py
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
import psycopg2
from migrate_to_rds import load_env, migrate_table, build_index, SCHEMA, KEEPALIVE

# SQLite's SUM(bool) must become SUM((bool)::int) in Postgres; columns are lowercase in RDS.
CONSENSUS_VIEW = f"""
CREATE OR REPLACE VIEW {SCHEMA}.stress_consensus AS
SELECT gene, domain, condition_class, condition_name,
       SUM((effect_sign='pos')::int) AS n_resistance,
       SUM((effect_sign='neg')::int) AS n_sensitising,
       COUNT(DISTINCT screen_id)      AS n_screens,
       SUM((effect_sign='pos')::int) - SUM((effect_sign='neg')::int) AS net,
       string_agg(DISTINCT screen_id, ',') AS screens
FROM {SCHEMA}.stress_facts
GROUP BY gene, domain, condition_class, condition_name
"""


def main():
    env = load_env()
    slite = sqlite3.connect(str(paths.DB))
    pg = psycopg2.connect(host=env["AWS_DB_HOST"], port=env.get("AWS_DB_PORT", "5432"),
                          user=env["AWS_DB_USER"], password=env["AWS_DB_PASSWORD"],
                          dbname=env["AWS_DB_NAME"], **KEEPALIVE)
    cur = pg.cursor()
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    pg.commit()

    metrics = {"tables": {}, "indexes": {}}
    migrate_table(slite, pg, cur, "stress_facts", metrics)
    build_index(pg, cur, "idx_sf_gene", "stress_facts", "gene", metrics)
    build_index(pg, cur, "idx_sf_gene_cond", "stress_facts", "gene, condition_name", metrics)
    cur.execute(f"DROP VIEW IF EXISTS {SCHEMA}.stress_consensus")
    cur.execute(CONSENSUS_VIEW)
    pg.commit()

    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.stress_facts")
    print("RDS reticle.stress_facts rows:", cur.fetchone()[0], flush=True)
    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.stress_consensus")
    print("RDS reticle.stress_consensus rows:", cur.fetchone()[0], flush=True)
    cur.execute(f"""SELECT gene, condition_name, n_resistance, n_sensitising, n_screens
                    FROM {SCHEMA}.stress_consensus
                    WHERE gene='ATM' AND condition_name='Olaparib'""")
    print("sanity ATM/Olaparib (should be resistance→0, sensitising~19):", cur.fetchone(), flush=True)
    pg.close(); slite.close()


if __name__ == "__main__":
    main()
