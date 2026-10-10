"""Save a menu as a new version. Old prices are left as they were."""

from datetime import timedelta

from app.extensions import db
from app.menu_costing.catalog import ALL_STORES
from app.menu_costing.models import MenuItemPrice, MenuVersion


def version_dicts():
    rows = (
        MenuVersion.query.order_by(MenuVersion.effective_from.desc(), MenuVersion.id.desc())
        .all()
    )
    payload = []
    for version in rows:
        payload.append(
            {
                "id": version.id,
                "city": version.city,
                "channel": version.channel,
                "store_scope": version.store_scope,
                "effective_from": version.effective_from,
                "effective_to": version.effective_to,
                "source": version.source,
                "items": [
                    {"item": price.item, "category": price.category, "price": price.price}
                    for price in version.prices
                ],
            }
        )
    return payload


def save_version(*, city, channel, store_scope, effective_from, source, items):
    scope = (store_scope or "").strip() or ALL_STORES
    still_open = MenuVersion.query.filter_by(
        city=city,
        channel=channel,
        store_scope=scope,
        effective_to=None,
    ).all()
    for previous in still_open:
        if previous.effective_from < effective_from:
            previous.effective_to = effective_from - timedelta(days=1)
    version = MenuVersion(
        city=city,
        channel=channel,
        store_scope=scope,
        effective_from=effective_from,
        effective_to=None,
        source=source or "",
    )
    db.session.add(version)
    db.session.flush()
    for row in items:
        db.session.add(
            MenuItemPrice(
                version_id=version.id,
                item=row["item"],
                category=row.get("category") or "",
                price=row.get("price"),
            )
        )
    db.session.commit()
    return version
