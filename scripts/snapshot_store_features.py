"""Write this month's store feature snapshot at each store's Google pin."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.location_model import write_snapshot


def main():
    parser = argparse.ArgumentParser(description="Snapshot trading-store features.")
    parser.add_argument("--month", default="", help="YYYY-MM. Blank uses the latest sales month.")
    args = parser.parse_args()
    path = write_snapshot(args.month or None)
    print(path)


if __name__ == "__main__":
    main()
