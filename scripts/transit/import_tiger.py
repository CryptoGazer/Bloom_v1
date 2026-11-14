#!/usr/bin/env python3
"""Idempotently catch up Tiger Data from the logger's append-only CSV spool.

usage: python3 -I scripts/transit/import_tiger.py [--dir data/transit] [--batch-size 1000]
Requires TIGER_DATABASE_URL in the environment or the project .env file.
Existing rows are skipped by their primary keys, so this command is safe to rerun.
"""
import argparse
import csv
import importlib.util
import os
import sys
from pathlib import Path

if __package__:
    from .tiger_store import TigerStore
else:  # exact-path import keeps working under the logger's documented ``python -I`` invocation
    _tiger_spec = importlib.util.spec_from_file_location("transit_tiger_store", Path(__file__).with_name("tiger_store.py"))
    _tiger_module = importlib.util.module_from_spec(_tiger_spec)
    _tiger_spec.loader.exec_module(_tiger_module)
    TigerStore = _tiger_module.TigerStore

ROOT = Path(__file__).resolve().parents[2]


def load_env(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def batches(path, size):
    if not path.exists():
        return
    with path.open(encoding="utf-8", newline="") as fh:
        batch = []
        for row in csv.DictReader(fh):
            batch.append(row)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch


def main():
    load_env(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(ROOT / "data/transit"))
    ap.add_argument("--batch-size", type=int, default=1000)
    args = ap.parse_args()
    if args.batch_size < 1:
        ap.error("--batch-size must be positive")
    dsn = os.environ.get("TIGER_DATABASE_URL", "").strip()
    if not dsn:
        sys.exit("TIGER_DATABASE_URL is not set in the environment or .env")

    source = Path(args.dir)
    store = TigerStore(dsn)
    vehicle_count = poll_count = 0
    try:
        for batch in batches(source / "vehicles.csv", args.batch_size) or ():
            store.write_or_raise(vehicles=batch)
            vehicle_count += len(batch)
            print(f"tiger: processed {vehicle_count} vehicle fixes", flush=True)
        for batch in batches(source / "polls.csv", args.batch_size) or ():
            store.write_or_raise(polls=batch)
            poll_count += len(batch)
            print(f"tiger: processed {poll_count} polls", flush=True)
    finally:
        store.close()
    print(f"tiger: catch-up complete; vehicle fixes={vehicle_count}, polls={poll_count}")


if __name__ == "__main__":
    main()
