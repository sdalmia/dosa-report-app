"""Names an owner sees. Codes and closed outlets stay off the page."""

from app.store_master import display_name_for

_HIDDEN = ("faridabad", "chattarpur", "gk1", "gk 1")


def hidden_store(label):
    folded = str(label or "").casefold()
    return any(token in folded for token in _HIDDEN)


def public_name(label):
    if hidden_store(label):
        return ""
    name = display_name_for(label)
    if "rosedale" in name.casefold():
        return "Rosedale Plaza (partly open)"
    return name
