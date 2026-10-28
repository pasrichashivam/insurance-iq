"""Run a read-only SQL query against the Cardinal Ridge database and print the rows (for validating AI answers).

    python insurance_data/run_sql.py "SELECT line, COUNT(*) FROM claims_current GROUP BY line"
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "backend" / "data" / "cardinal_ridge.db"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(sys.argv[1]).fetchall()
    if rows:
        print(" | ".join(rows[0].keys()))
    for r in rows[:100]:
        print(" | ".join(str(v) for v in tuple(r)))
    print(f"({len(rows)} row(s))")


if __name__ == "__main__":
    main()
