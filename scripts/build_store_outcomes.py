"""Join the feature snapshot to Posist and Famepilot outcomes."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.location_model import write_outcomes


def main():
    parser = argparse.ArgumentParser(description="Build store outcome rows.")
    parser.add_argument("--month", default="", help="YYYY-MM. Blank uses the latest sales month.")
    args = parser.parse_args()
    path = write_outcomes(args.month or None)
    print(path)


if __name__ == "__main__":
    main()
