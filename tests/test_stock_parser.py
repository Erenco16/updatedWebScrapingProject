"""
tests/test_stock_parser.py

Regression coverage for every Hafele price/stock HTML shape we've seen
produce a bad DB row. Grouped by scenario:

Happy paths
    - Simple single-row in-stock variant
    - Multi-row with thousands-separator qty  (``"13.600"`` -> 13600)
    - Multi-row where first "stokta mevcut" is noise and the real
      inventory row is further down

Sad paths (previously regressions)
    - ``tr.values-tr.order-qty`` (Type B / packaging-size rows) must
      not be read as inventory. Prior behaviour: parser returned
      ``("stokta mevcut", None)`` using Type B's status + Type B's
      "Ambalaj birimi 1" qty label.
    - When the real ``.availability-flag`` is empty, the fallback must
      NOT drift into the price block's ``<span class="perUnit">
      # Adet (ADT)</span>``. Prior behaviour: 3,855 rows got
      ``stok_durumu = '# Adet (ST)' / '# Set (GR)' / etc.``.
    - Rows whose availability-flag or qty text looks like a packaging
      label (``# Adet``, ``Ambalaj birimi 1``) must be rejected.
    - Empty Hafele body (status 200 with no content, discontinued SKUs)
      must produce (None, None) so the Dinler fallback fires.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCRAPLING_STORAGE_DIR", "/tmp")

from spiders.hafele_parsing import (
    _parse_hafele_qty,
    _parse_bom_qty,
    _looks_like_unit_label,
    _is_order_qty_row,
    parse_stock_from_values_tr,
    parse_stock_from_bom,
    parse_stock_fallback,
    parse_price_from_html,
    extract_article_numbers,
)
from scrapling import Selector


# ─── _parse_hafele_qty ─────────────────────────────────────────────

class TestParseHafeleQty:
    def test_simple_small(self):
        assert _parse_hafele_qty("5") == 5
    def test_trailing_whitespace_and_newline(self):
        assert _parse_hafele_qty("7 \n") == 7
    def test_thousands_sep(self):
        assert _parse_hafele_qty("13.600") == 13600
    def test_thousands_sep_with_trailing_ws(self):
        assert _parse_hafele_qty("1.568 \n") == 1568
    def test_nbsp_separated_thousands(self):
        assert _parse_hafele_qty("\xa01.234\xa0") == 1234
    def test_empty_returns_none(self):
        assert _parse_hafele_qty("") is None
    def test_none_returns_none(self):
        assert _parse_hafele_qty(None) is None
    def test_packaging_label_returns_none(self):
        assert _parse_hafele_qty("Ambalaj birimi 1") is None
    def test_unit_label_returns_none(self):
        assert _parse_hafele_qty("# Adet (ST)") is None


# ─── _looks_like_unit_label ────────────────────────────────────────

class TestUnitLabelDetection:
    def test_adet_pattern(self):
        assert _looks_like_unit_label("# Adet (ST)")
    def test_set_gr_pattern(self):
        assert _looks_like_unit_label("# Set (GR)")
    def test_cift_pattern(self):
        assert _looks_like_unit_label("# Çift (Çift)")
    def test_metre_pattern(self):
        assert _looks_like_unit_label("# Metre (M)")
    def test_ambalaj_label(self):
        assert _looks_like_unit_label("Ambalaj birimi 1")
    def test_normal_status_is_not_label(self):
        assert not _looks_like_unit_label("stokta mevcut")
    def test_normal_qty_is_not_label(self):
        assert not _looks_like_unit_label("13.600")
    def test_empty_is_not_label(self):
        assert not _looks_like_unit_label("")


# ─── _is_order_qty_row ─────────────────────────────────────────────

class TestOrderQtyDetection:
    def test_plain_values_tr_is_inventory(self):
        row = Selector(content='<tr class="values-tr"><td/></tr>', adaptive=False).css("tr")[0]
        assert not _is_order_qty_row(row)
    def test_order_qty_values_tr_is_not_inventory(self):
        row = Selector(content='<tr class="values-tr order-qty"><td/></tr>', adaptive=False).css("tr")[0]
        assert _is_order_qty_row(row)


# ─── parse_stock_from_values_tr happy paths ────────────────────────

class TestParseStockHappy:
    def test_single_row_in_stock(self):
        html = ("""<html><body><table>
<tr class="values-tr">
  <td class="qty-available">5 </td>
  <td class="packaging-available">5 x Ambalaj birimi 1</td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">stokta mevcut </span>
  </td>
</tr>
</table></body></html>""").encode("utf-8")
        assert parse_stock_from_values_tr(html) == ("stokta mevcut", 5)

    def test_thousands_separator_qty(self):
        html = ("""<html><body><table>
<tr class="values-tr">
  <td class="qty-available">13.600 </td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">stokta mevcut </span>
  </td>
</tr>
</table></body></html>""").encode("utf-8")
        assert parse_stock_from_values_tr(html) == ("stokta mevcut", 13600)

    def test_multi_row_prefers_stokta_mevcut(self):
        html = ("""<html><body><table>
<tr class="values-tr">
  <td class="qty-available">6.400 </td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">istek üzerine</span></td></tr>
<tr class="values-tr">
  <td class="qty-available">13.600 </td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">stokta mevcut</span></td></tr>
</table></body></html>""").encode("utf-8")
        assert parse_stock_from_values_tr(html) == ("stokta mevcut", 13600)

    def test_in_stock_without_qty_then_with_qty_prefers_qty_row(self):
        """A ``stokta mevcut`` row with unparseable qty must NOT win
        over a later ``stokta mevcut`` row with real qty."""
        html = ("""<html><body><table>
<tr class="values-tr">
  <td class="qty-available">Ambalaj birimi 200</td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">stokta mevcut</span></td></tr>
<tr class="values-tr">
  <td class="qty-available">42</td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">stokta mevcut</span></td></tr>
</table></body></html>""").encode("utf-8")
        assert parse_stock_from_values_tr(html) == ("stokta mevcut", 42)


# ─── parse_stock_from_values_tr sad paths (regressions) ───────────

class TestParseStockRegressions:
    def test_type_b_order_qty_rows_ignored_with_in_stock_type_a(self):
        """SKU=00299032 shape: Type A row has real status, Type B rows
        contain 'stokta mevcut' noise. We must return Type A."""
        html = ("""<html><body><table>
<tr class="values-tr">
  <td class="qty-available">20.000 </td>
  <td class="packaging-available">2.000 x Ambalaj birimi 10</td>
  <td class="requestedPackageStatus">
    <span class="availability-flag">istek üzerine </span></td></tr>
<tr class="values-tr order-qty">
  <td class=" qty-available">Ambalaj birimi 1</td>
  <td colspan="2" class="availablePackageStatus">
    <span class="availability-flag">stokta mevcut</span></td></tr>
<tr class="values-tr order-qty">
  <td class=" qty-available">Ambalaj birimi 10</td>
  <td colspan="2" class="availablePackageStatus">
    <span class="availability-flag">stokta mevcut</span></td></tr>
</table></body></html>""").encode("utf-8")
        # Prior buggy behaviour returned ("stokta mevcut", None).
        # The real inventory status for this SKU is "istek üzerine".
        status, qty = parse_stock_from_values_tr(html)
        assert status == "istek üzerine", status
        assert qty == 20000, qty

    def test_type_b_alone_returns_none(self):
        """Response that has ONLY Type B rows (no inventory row) must
        produce (None, None) so Dinler fallback can take over."""
        html = ("""<html><body><table>
<tr class="values-tr order-qty">
  <td class=" qty-available">Ambalaj birimi 1</td>
  <td colspan="2" class="availablePackageStatus">
    <span class="availability-flag">stokta mevcut</span></td></tr>
</table></body></html>""").encode("utf-8")
        assert parse_stock_from_values_tr(html) == (None, None)

    def test_empty_body_returns_none(self):
        """Discontinued-SKU shape: empty body, nothing to parse."""
        assert parse_stock_from_values_tr(b"") == (None, None)


# ─── parse_stock_fallback ──────────────────────────────────────────

class TestParseStockFallback:
    def test_populated_fallback_flag(self):
        html = ("""<html><body>
<div id="productAvailabilityInformation">
  <p><span class="availability-flag">istek üzerine</span></p>
</div></body></html>""").encode("utf-8")
        assert parse_stock_fallback(html) == "istek üzerine"

    def test_empty_fallback_flag_returns_none(self):
        html = ("""<html><body>
<div id="productAvailabilityInformation">
  <p><span class="availability-flag"></span></p>
</div></body></html>""").encode("utf-8")
        assert parse_stock_fallback(html) is None

    def test_adaptive_drift_into_perunit_is_rejected(self):
        """SKU=90253971 shape: productAvailabilityInformation has an
        empty availability-flag. The DOM also contains a ``perUnit``
        span (``# Adet (ADT)``) inside the price block. The old
        adaptive-match parser returned ``# Adet (ADT)`` as stok_durumu.
        After the fix, parse_stock_fallback must return None so the
        Dinler fallback can take over.
        """
        html = ("""<html><body>
<div class="pricedisplay">
  <p class="price">
    <span class="price">793,12 TL</span>
    <span class="perUnit"># Adet (ADT)</span>
  </p>
</div>
<div id="productAvailabilityInformation">
  <p><span class="availability-flag" style="color:"></span></p>
</div>
</body></html>""").encode("utf-8")
        result = parse_stock_fallback(html)
        assert result is None, f"adaptive drift re-emerged: got {result!r}"

    def test_unit_label_directly_in_fallback_is_rejected(self):
        """Even if (somehow) the exact selector returns a unit label,
        the belt-and-braces filter rejects it."""
        html = ("""<html><body>
<div id="productAvailabilityInformation">
  <p><span class="availability-flag"># Adet (ST)</span></p>
</div></body></html>""").encode("utf-8")
        assert parse_stock_fallback(html) is None


# ─── parse_price_from_html isolation ───────────────────────────────

class TestParsePriceIsolation:
    def test_price_only_extracts_price_spans(self):
        html = ("""<html><body>
<div class="pricedisplay">
  <p class="price">
    <span class="price">793,12 TL</span>
    <span class="perUnit"># Adet (ADT)</span>
  </p>
  <p class="price">
    <span class="price">1.586,24 TL</span>
    <span class="perUnit"># Adet (ADT)</span>
  </p>
  <p class="price">
    <span class="price">1.057,50 TL</span>
  </p>
</div></body></html>""").encode("utf-8")
        prices = parse_price_from_html(html)
        assert prices["kdv_haric_net_fiyat"] == "793,12 TL"
        assert prices["kdv_haric_satis_fiyati"] == "1.586,24 TL"
        assert prices["kdv_haric_tavsiye_edilen_perakende_fiyat"] == "1.057,50 TL"


# ─── _parse_bom_qty ────────────────────────────────────────────────

class TestParseBomQty:
    def test_simple_integer(self):
        assert _parse_bom_qty("20000 Adet (ADT)") == 20000
    def test_thousands_separator(self):
        assert _parse_bom_qty("13.600 Çift (ÇFT)") == 13600
    def test_leading_whitespace(self):
        assert _parse_bom_qty("\n20000 Adet (ADT) \n") == 20000
    def test_set_kit_unit(self):
        assert _parse_bom_qty("20000 Kit (KIT)") == 20000
    def test_empty_returns_none(self):
        assert _parse_bom_qty("") is None
    def test_unit_label_without_qty_returns_none(self):
        assert _parse_bom_qty("Adet (ADT)") is None


# ─── parse_stock_from_bom ──────────────────────────────────────────

class TestParseStockBom:
    def test_single_in_stock_bom_component(self):
        html = ("""<html><body><table>
<tr><td>
<div class="bomArticleStatus">
  <span class="availability-flag">stokta mevcut</span>
</div>
</td>
<td class="bomArticleStatus"> 20000 Adet (ADT) </td>
</tr></table></body></html>""").encode("utf-8")
        assert parse_stock_from_bom(html) == ("stokta mevcut", 20000)

    def test_two_components_prefers_stokta_mevcut(self):
        """SKU=58821411 shape: first component is 'istek üzerine', second
        is 'stokta mevcut'. Priority rule picks the mevcut row."""
        html = ("""<html><body><table>
<tr><td>
<div class="bomArticleStatus"><span class="availability-flag">istek üzerine</span></div>
</td>
<td class="bomArticleStatus"> 20000 Adet (ADT) </td>
</tr>
<tr><td>
<div class="bomArticleStatus"><span class="availability-flag">stokta mevcut</span></div>
</td>
<td class="bomArticleStatus"> 20000 Adet (ADT) </td>
</tr></table></body></html>""").encode("utf-8")
        assert parse_stock_from_bom(html) == ("stokta mevcut", 20000)

    def test_bom_thousands_separator_qty(self):
        html = ("""<html><body><table>
<tr><td>
<div class="bomArticleStatus"><span class="availability-flag">stokta mevcut</span></div>
</td>
<td class="bomArticleStatus"> 13.600 Çift (ÇFT) </td>
</tr></table></body></html>""").encode("utf-8")
        assert parse_stock_from_bom(html) == ("stokta mevcut", 13600)

    def test_no_bom_elements_returns_none(self):
        html = b"<html><body></body></html>"
        assert parse_stock_from_bom(html) == (None, None)

    def test_bom_without_qty_td_falls_back_to_none(self):
        html = ("""<html><body>
<div class="bomArticleStatus"><span class="availability-flag">stokta mevcut</span></div>
</body></html>""").encode("utf-8")
        status, qty = parse_stock_from_bom(html)
        # No td -> qty None; status still extracted
        assert status == "stokta mevcut"
        assert qty is None

    def test_bom_rejects_unit_label_pollutant_in_flag(self):
        """Belt-and-braces: if adaptive drift ever puts a unit label
        in the flag span, reject it rather than storing garbage."""
        html = ("""<html><body>
<div class="bomArticleStatus"><span class="availability-flag"># Adet (ADT)</span></div>
<td class="bomArticleStatus"> 20000 Adet (ADT) </td>
</body></html>""").encode("utf-8")
        assert parse_stock_from_bom(html) == (None, None)


# ─── values_tr parser must NOT drift onto BOM markup ─────────────

class TestValuesTrNotDriftingToBom:
    def test_bom_only_body_returns_none_from_values_tr(self):
        """If the response has only BOM markup (no tr.values-tr rows),
        parse_stock_from_values_tr must return (None, None) so the
        BOM parser is given a chance. Prior adaptive drift falsely
        returned ('stokta mevcut', None)."""
        html = ("""<html><body><table>
<tr><td>
<div class="bomArticleStatus"><span class="availability-flag">stokta mevcut</span></div>
</td>
<td class="bomArticleStatus"> 20000 Adet (ADT) </td>
</tr></table></body></html>""").encode("utf-8")
        assert parse_stock_from_values_tr(html) == (None, None)


# ─── Empty-body-200 Cloudflare soft-reject behaviour ───────────────

class TestEmptyBody200Handling:
    """These are properties of the scraper spider's ``parse_product_api``
    behaviour, exercised indirectly through the parser functions. The
    goal is to document the contract: an empty response body must
    produce (None, None) from every parser so the scraper's own
    requeue-as-network-attempt path takes over, instead of falling
    through to Dinler. (Dinler sees an "unknown" SKU and happily says
    "in stock" with no stockAmount, producing a bad Excel row.)
    """

    def test_zero_byte_body(self):
        assert parse_stock_from_values_tr(b"") == (None, None)
        assert parse_stock_from_bom(b"") == (None, None)
        assert parse_stock_fallback(b"") is None

    def test_whitespace_only_body(self):
        assert parse_stock_from_values_tr(b"   \n  ") == (None, None)
        assert parse_stock_from_bom(b"   \n  ") == (None, None)

    def test_tiny_fragment_body(self):
        """Hafele's soft-reject sometimes returns a tiny token like
        ``" \n"``. Must parse to nothing."""
        assert parse_stock_from_values_tr(b" \n") == (None, None)
        assert parse_stock_from_bom(b" \n") == (None, None)
        assert parse_stock_fallback(b" \n") is None
