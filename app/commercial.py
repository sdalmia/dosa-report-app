"""Swiggy and Zomato commission.

Both platforms charge commission on the net value of the bill, then GST on
that commission. Dine-in and takeaway are not charged this way. When a payout
or ads file is on disk, that actual is preferred and the gap versus this rule
is shown beside it.
"""

from pathlib import Path

AGGREGATOR_COMMISSION_PCT = 21
GST_ON_COMMISSION_PCT = 18
DELIVERY_CHANNELS = frozenset({"swiggy", "zomato"})


def effective_commission_pct():
    """21% plus 18% GST on that commission, as a percent of net."""
    return (AGGREGATOR_COMMISSION_PCT * (100 + GST_ON_COMMISSION_PCT)) / 100


def is_delivery_channel(name):
    return str(name or "").strip().casefold() in DELIVERY_CHANNELS


def split_delivery_net(net):
    """Commission, GST on the commission, and what is left of net.

    Returns None when net is missing. A real zero is kept. This is not for
    dine-in or takeaway.
    """
    if net is None:
        return None
    net_value = float(net)
    commission = net_value * AGGREGATOR_COMMISSION_PCT / 100
    gst = commission * GST_ON_COMMISSION_PCT / 100
    drag = commission + gst
    return {
        "net": net_value,
        "commission": commission,
        "gst_on_commission": gst,
        "drag": drag,
        "realisation": net_value - drag,
        "effective_pct": effective_commission_pct(),
    }


def channel_contribution(net, food=None, packaging=None):
    """Net minus commission drag, food cost, and packaging.

    Missing food or packaging is named and left out. It is not treated as zero.
    """
    take = split_delivery_net(net)
    if take is None:
        return None
    missing = []
    total = take["realisation"]
    if food is None:
        missing.append("food cost")
    else:
        total -= float(food)
    if packaging is None:
        missing.append("packaging")
    else:
        total -= float(packaging)
    take["contribution"] = total
    take["missing"] = missing
    return take


def basis_sentence():
    pct = effective_commission_pct()
    return (
        f"Swiggy and Zomato charge {AGGREGATOR_COMMISSION_PCT:g}% commission plus "
        f"{GST_ON_COMMISSION_PCT:g}% GST on that commission, on the net value of each bill. "
        f"That is {pct:.2f}% of net. It is not applied to dine-in or takeaway."
    )


def payout_files(root=None):
    """Swiggy or Zomato payout and ad files under data/. Channel gross is not a payout."""
    base = Path(root) if root else Path(__file__).resolve().parents[1] / "data"
    if not base.is_dir():
        return []
    found = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".csv", ".xlsx", ".xls", ".json"}:
            continue
        name = path.name.casefold()
        if "payout" in name or ("swiggy" in name and "ad" in name) or ("zomato" in name and "ad" in name):
            found.append(path)
    return sorted(found)
