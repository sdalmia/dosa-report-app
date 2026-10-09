"""Food cost and vendor panel.

Reads data/procurement and Posist gross. Blank cells stay blank.
Home-page tiles stay importable as app.procurement.procurement_tiles.
"""

from app.procurement.drops import procurement_tiles

__all__ = ["procurement_tiles"]
