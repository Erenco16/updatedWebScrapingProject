"""
spiders/models.py

Typed data structures (Pydantic) for everything that flows between the
scraper -> item pipeline -> SQLite writer, plus helpers that are shared
across the whole pipeline (SKU dotted-format conversion for the Dinler
fallback API and the final Excel report).

Why Pydantic:
- One schema definition the whole project reads from instead of dict
  keys sprinkled across spiders/db_writer/reporter.
- Rejects garbage at the scraper boundary (bad types, missing SKU, ...)
  instead of surfacing it as a corrupted row later in SQLite.
- `.model_dump()` round-trips cleanly through JSON for Redis handoff.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


_SKU_DIGITS_ONLY_RE = re.compile(r"\D+")


def format_sku_with_dots(sku: object) -> str:
    """Convert an 8-digit Hafele SKU to the dotted ``XXX.XX.XXX`` format
    that Dinler's stock API expects and that the end-user Excel report
    needs to display (e.g. ``90198256`` -> ``901.98.256``).

    Non-8-digit SKUs (shorter codes, codes already containing dots, empty
    values) are returned stringified-but-otherwise-unchanged so this is
    always safe to call on arbitrary ``sku`` columns.
    """
    if sku is None:
        return ""
    s = str(sku).strip()
    if not s:
        return s
    digits = _SKU_DIGITS_ONLY_RE.sub("", s)
    if len(digits) == 8:
        return f"{digits[:3]}.{digits[3:5]}.{digits[5:]}"
    return s


class ProductItem(BaseModel):
    """One scraped Hafele variant row.

    Mirrors the SQLite ``products`` table columns 1:1 so ``db_writer`` can
    just call ``model_dump()`` and hand the dict to ``database.save_product``
    without any additional mapping. Validation happens at the scraper
    boundary (bad types -> ValidationError raised in the spider, not an
    opaque UNIQUE/NOT NULL failure in SQLite).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(..., min_length=1, description="Hafele variant SKU, digits-only")
    stock_code: str = Field(..., min_length=1, description="Mirrors sku for the Excel export")
    product_name: Optional[str] = Field(default=None, description="Catalog name of the master")
    product_description: str = Field(default="", description="name + subline, free text")

    kdv_haric_net_fiyat: Optional[str] = None
    kdv_haric_tavsiye_edilen_perakende_fiyat: Optional[str] = None
    kdv_haric_satis_fiyati: Optional[str] = None
    currency: str = Field(default="TRY", description="Hafele TR always prices in TRY")

    stok_durumu: Optional[str] = Field(
        default=None,
        description="Turkish stock-status label; falls back to Dinler API when unknown.",
    )
    stock_status: Optional[str] = Field(
        default=None,
        description="Normalized In Stock / Out of Stock / Unknown; derived from stok_durumu.",
    )
    stock_amount: Optional[int] = Field(default=None, ge=0)

    is_group_product: int = Field(default=0, ge=0, le=1)
