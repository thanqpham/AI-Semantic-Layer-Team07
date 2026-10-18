"""Setup Target Database Script for New Environment.

Pure Python setup tool with ZERO external package requirements.
Works across Windows, Linux, and macOS.

Usage:
    python scripts/setup_target_db.py
"""

import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PG_SCHEMA_PATH = os.path.join(DATA_DIR, "golden_retail_schema_pg.sql")
PG_SEED_PATH = os.path.join(DATA_DIR, "golden_retail_seed_pg.sql")


def run_cmd(cmd: list[str], input_str: str | None = None) -> tuple[bool, str]:
    """Run a command without shell interpolation, with optional input."""
    try:
        res = subprocess.run(
            cmd,
            input=input_str,
            text=True,
            encoding="utf-8",
            capture_output=True,
            shell=False,
            check=True
        )

        return True, res.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr or e.stdout
    except OSError as e:
        return False, str(e)


def get_postgres_container() -> tuple[str, str]:
    """Resolve the active Compose PostgreSQL container and its configured user."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ok, out = run_cmd([
        "docker", "compose", "--project-directory", project_dir,
        "ps", "-q", "postgres",
    ])
    containers = out.split() if ok else []
    if len(containers) != 1:
        print(f"Error: Cannot find one running Compose postgres container: {out.strip()}")
        print("Start PostgreSQL with docker compose up -d postgres first.")
        sys.exit(1)
    container = containers[0]
    ok, out = run_cmd(["docker", "exec", container, "printenv", "POSTGRES_USER"])
    if not ok or not out.strip():
        print(f"Error: Cannot read PostgreSQL user: {out.strip()}")
        sys.exit(1)
    return container, out.strip()


def main() -> None:
    print("🚀 Setting up Golden Retail Target Database (36 Tables, 8.5MB Seed Data)...")

    container_name, postgres_user = get_postgres_container()
    psql = ["docker", "exec", "-i", container_name, "psql", "-v", "ON_ERROR_STOP=1", "-U", postgres_user]

    # 0. Ensure schema & seed SQL files exist (auto-generate if missing)
    if not os.path.exists(PG_SCHEMA_PATH) or not os.path.exists(PG_SEED_PATH):
        print("🌱 Seed data SQL file missing. Auto-generating seed data...")
        scripts_dir = os.path.dirname(__file__)
        gen_py = os.path.join(scripts_dir, "seed_data_generator.py")
        conv_py = os.path.join(scripts_dir, "convert_to_postgres.py")
        for script in (gen_py, conv_py):
            ok, out = run_cmd([sys.executable, script])
            if not ok:
                print(f"Error: Failed to generate seed SQL: {out}")
                sys.exit(1)

    # 1. Terminate existing sessions to golden_retail_db if any
    run_cmd(psql + ["-d", "postgres", "-c", "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'golden_retail_db' AND pid <> pg_backend_pid();"])

    # 2. Re-create database golden_retail_db
    print("⚙️  Creating database 'golden_retail_db'...")
    ok, out = run_cmd(psql + ["-d", "postgres", "-c", "DROP DATABASE IF EXISTS golden_retail_db;"])
    if not ok:
        print(f"Error: Failed to reset database: {out}")
        sys.exit(1)
    ok, out = run_cmd(psql + ["-d", "postgres", "-c", "CREATE DATABASE golden_retail_db;"])
    if not ok:
        print(f"❌ Failed to create database: {out}")
        sys.exit(1)
    print("✅ Created database 'golden_retail_db'.")

    # 3. Import Schema
    print("⏳ Importing 36 DDL tables from golden_retail_schema_pg.sql...")
    with open(PG_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    ok, out = run_cmd(psql + ["-d", "golden_retail_db"], input_str=schema_sql)
    if not ok:
        print(f"❌ Failed to import schema: {out}")
        sys.exit(1)
    print("✅ Successfully imported 36 DDL tables!")

    # 4. Import Seed Dataset
    print("⏳ Importing 8.5 MB seed dataset from golden_retail_seed_pg.sql...")
    with open(PG_SEED_PATH, "r", encoding="utf-8") as f:
        seed_sql = f.read()
    ok, out = run_cmd(psql + ["-d", "golden_retail_db"], input_str=seed_sql)
    if not ok:
        print(f"❌ Failed to import seed dataset: {out}")
        sys.exit(1)
    print("✅ Successfully imported 8.5 MB seed dataset (5,000 Orders, 1,000 Customers, 8,000 Sessions)!")

    print("\n🎉 Target Database setup completed 100% successfully!")
    print("📌 Connection settings for testing:")
    print(f"   Database: golden_retail_db; user: {postgres_user}")
    print("   Use the password and published port from your active Compose configuration.")


if __name__ == "__main__":
    main()
