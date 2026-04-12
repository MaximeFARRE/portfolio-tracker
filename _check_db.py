"""Check DB data availability for analytics."""
import sqlite3

conn = sqlite3.connect("patrimoine.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT id, name FROM people").fetchall()
for r in rows:
    pid = r["id"]
    name = r["name"]
    snaps = conn.execute(
        "SELECT COUNT(*) as c FROM patrimoine_snapshots_weekly WHERE person_id=?",
        (pid,),
    ).fetchone()["c"]
    
    assets = conn.execute(
        "SELECT COUNT(DISTINCT a.symbol) as c FROM transactions t "
        "JOIN assets a ON a.id=t.asset_id "
        "WHERE t.person_id=? AND t.type='ACHAT'",
        (pid,),
    ).fetchone()["c"]
    
    prices = conn.execute("SELECT COUNT(*) as c FROM asset_prices_weekly").fetchone()["c"]
    
    print(f"Person {pid} ({name}): {snaps} snapshots, {assets} assets traded, {prices} weekly prices total")

conn.close()
