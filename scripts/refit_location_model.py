"""Fit one pooled location model and save it as proposed."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.location_model import write_refit


def main():
    parser = argparse.ArgumentParser(description="Refit the location model.")
    parser.add_argument("--month", default="", help="YYYY-MM. Blank uses the latest sales month.")
    parser.add_argument("--version", default="", help="Model name, such as v2026-10b. Blank uses vYYYY-MM.")
    args = parser.parse_args()
    path = write_refit(args.month or None, version=args.version or None)
    print(path)


if __name__ == "__main__":
    main()
