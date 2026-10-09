#!/usr/bin/env python3
"""Load per-store Posist folders into the menu-mix and channel-sales files.

Drop a new store folder under data/posist_raw and run this again:

    python3 scripts/load_posist_raw.py

A folder is named by store code (0004, 002, 01-0001, 02-0013). It can hold
store.txt, menu_items_<from>_to_<to>.xlsx (two halves are added together),
source_range_<from>_to_<to>.tsv, and source_daily_<from>_to_<to>.tsv.
A partial folder is loaded for the files it actually has. Stores with no
folder stay off these files; the pages show them as data coming.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.menu_ops.loader import load_regions, posist_path
from app.menu_ops.posist_raw import load_posist_raw, posist_raw_directory, write_outputs


def main():
    parser = argparse.ArgumentParser(description="Load per-store Posist folders.")
    parser.add_argument("--raw", type=Path, default=posist_raw_directory())
    parser.add_argument("--posist", type=Path, default=posist_path())
    parser.add_argument("--menu-dir", type=Path, default=ROOT / "data" / "menu")
    parser.add_argument("--channel-dir", type=Path, default=ROOT / "data" / "channels")
    args = parser.parse_args()
    regions, warnings = load_regions(args.posist)
    for warning in warnings:
        print(warning)
    loaded = load_posist_raw(args.raw, list(regions))
    for warning in loaded["warnings"]:
        print(warning)
    menu_path, channel_path = write_outputs(loaded, args.menu_dir, args.channel_dir)
    menu_stores = sum(1 for row in loaded["stores"] if row["menu"])
    channel_stores = sum(1 for row in loaded["stores"] if row["channels"])
    print(f"Menu mix: {menu_stores} stores" + (f" -> {menu_path.name}" if menu_path else ""))
    print(f"Delivery vs dine-in: {channel_stores} stores" + (f" -> {channel_path.name}" if channel_path else ""))
    print(f"Data coming for menu: {len(regions) - menu_stores} of {len(regions)} stores")
    print(f"Data coming for delivery: {len(regions) - channel_stores} of {len(regions)} stores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
