"""Initialize the local SQLite database from schema.sql.

Usage:
    python init_db.py
"""

import os
import sqlite3

DB_PATH = "donorbridge.db"
SCHEMA_PATH = "schema.sql"


def main() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print(f"Initialized {DB_PATH} from {SCHEMA_PATH}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
