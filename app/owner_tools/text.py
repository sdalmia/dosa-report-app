"""Plain-text morning brief. Nothing is sent from this render."""


def _show(figure):
    if not figure or figure.get("value") is None or not figure.get("text"):
        return "blank"
    return figure["text"]


def _line(label, figure):
    return f"{label}: {_show(figure)}"


def render_brief_text(brief):
    lines = [
        "Dosa Coffee morning brief",
        brief.get("as_of_label") or "No date",
        "Sales are gross.",
        "",
    ]
    if brief.get("empty"):
        lines.append(brief["empty"])
        return "\n".join(lines).rstrip() + "\n"
    network = brief["network"]
    lines.extend(
        [
            "Network",
            _line("Gross", network["gross"]),
            _line("Bills", network["bills"]),
            f"APB: {_show(network['apb'])}",
            f"Gross vs last week: {_show(network['gross_change_pct'])}",
            f"Bills vs last week: {_show(network['bills_change_pct'])}",
            "",
            "By store",
        ]
    )
    for region in brief["regions"]:
        lines.append(region["name"])
        for store in region["stores"]:
            lines.append(f"- {store['label']}")
            lines.append(f"  Gross {_show(store['gross'])} ({_show(store['gross_change_pct'])} vs last week)")
            lines.append(f"  Bills {_show(store['bills'])} ({_show(store['bills_change_pct'])} vs last week)")
            lines.append(f"  APB: {_show(store['apb'])}")
        lines.append("")
    lines.append("Lowest versus forecast")
    if brief.get("worst_vs_mid_empty"):
        lines.append(brief["worst_vs_mid_empty"])
    for index, item in enumerate(brief["worst_vs_mid"], start=1):
        lines.append(
            f"{index}. {item['label']} — gross {_show(item['gross'])} vs mid {_show(item['mid'])} ({_show(item['variance_pct'])})"
        )
    lines.append("")
    lines.append("Lowest versus last week")
    if brief.get("worst_vs_last_week_empty"):
        lines.append(brief["worst_vs_last_week_empty"])
    for index, item in enumerate(brief["worst_vs_last_week"], start=1):
        lines.append(
            f"{index}. {item['label']} — gross {_show(item['gross'])} vs {_show(item['prior_gross'])} ({_show(item['variance_pct'])})"
        )
    lines.append("")
    lines.append("Food safety")
    if brief.get("food_safety_empty"):
        lines.append(brief["food_safety_empty"])
    for item in brief["food_safety"]:
        who = f"{item['store']}: " if item.get("store") else ""
        lines.append(f"- {who}{item['text']}")
    lines.append("")
    lines.append("Emergency")
    if brief.get("emergency_empty"):
        lines.append(brief["emergency_empty"])
    for item in brief["emergency"]:
        who = f"{item['store']}: " if item.get("store") else ""
        lines.append(f"- {who}{item['text']}")
    lines.append("")
    lines.append("Procurement")
    if brief.get("procurement_empty"):
        lines.append(brief["procurement_empty"])
    for item in brief["procurement"]:
        who = f"{item['store']}: " if item.get("store") else ""
        lines.append(f"- {who}{item['text']}".strip())
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
