"""The slug of a name: the key of a payee, a store and a product.

Shared by `normalize` (receipt text) and the `Catalog` (a payee typed by hand), so that
"Mercadona" typed by the user and "MERCADONA S.A." printed on a receipt meet in one place
only when their slugs match.
"""

import re
import unicodedata
from typing import Any


def strip(s: Any) -> str:
    """Remove accents."""
    text = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFD", text) if not "̀" <= c <= "ͯ")


def slug(s: Any) -> str:
    text = strip(s).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9а-яё]+", "-", text).strip("-")
