"""
scraper.py
----------
Responsible for:
- Fetching a single product page and routing to the correct handler
- Orchestrating the round-robin tab pool scrape across all products
- Retrying failed products after the main pass

Depends on: page_loader.py, product_handler.py
"""

import time
import random
from collections import deque
from bs4 import BeautifulSoup

from src.page_loader import (
    wait_for_page_ready,
    wait_for_element_or_error,
    detect_and_backoff_cloudflare,
)
from src.product_handler import handle_singular_product, handle_group_product

FETCH_FAILED = "FETCH_FAILED"

_FAILED_RESULT = {
    "kdv_haric_tavsiye_edilen_perakende_fiyat": FETCH_FAILED,
    "kdv_haric_net_fiyat":                      FETCH_FAILED,
    "kdv_haric_satis_fiyati":                   FETCH_FAILED,
    "stok_durumu":                              FETCH_FAILED,
    "stock_amount":                             FETCH_FAILED,
    "product_description":                      FETCH_FAILED,
}

_NOT_FOUND_RESULT = {
    "kdv_haric_tavsiye_edilen_perakende_fiyat": "urun hafele.com.tr de bulunmuyor",
    "kdv_haric_net_fiyat":                      "urun hafele.com.tr de bulunmuyor",
    "kdv_haric_satis_fiyati":                   "urun hafele.com.tr de bulunmuyor",
    "stok_durumu":                              "urun hafele.com.tr de bulunmuyor",
    "stock_amount":                             "urun hafele.com.tr de bulunmuyor",
    "product_description":                      "No description available",
}


def retrieve_product_data(driver, url: str, code: str, retries: int = 3) -> dict:
    """
    Navigate to a product URL, wait for meaningful DOM elements,
    and route to the correct handler based on product type.

    Improvements vs original:
    - Uses WebDriverWait instead of flat time.sleep(2)
    - Validates that price elements are present before committing a result
    - Re-navigates after Cloudflare backoff instead of just looping
    - Returns FETCH_FAILED sentinel on exhausted retries

    Args:
        driver:  Selenium WebDriver (already on the correct tab)
        url:     Full product API URL
        code:    Product stock code (used for "not found" message matching)
        retries: Max navigation attempts

    Returns:
        dict with product data, or FETCH_FAILED values on failure
    """
    for attempt in range(retries):
        try:
            print(f"  Navigating to {url} (attempt {attempt + 1}/{retries})")
            driver.get(url)
            wait_for_page_ready(driver)

            # If Cloudflare intercepted, re-navigate after backoff
            if detect_and_backoff_cloudflare(driver):
                driver.get(url)
                wait_for_page_ready(driver)

            html  = wait_for_element_or_error(driver)
            soup  = BeautifulSoup(html, "html.parser")

            # Product not found
            error_el = soup.find("p", class_="headlineStyle4")
            if error_el and f"{code} için aramanız başarısız oldu." in error_el.text:
                print(f"  ⚠ Product {code} not found on hafele.com.tr")
                return dict(_NOT_FOUND_RESULT)

            # Validate partial load — retry if no prices in DOM yet
            if not soup.select("span.price"):
                print(f"  ⚠ No price elements on attempt {attempt + 1} — retrying...")
                time.sleep(2 ** attempt)
                continue

            # Route to correct handler
            if soup.find("tr", id="productBomArticlesInformation"):
                return handle_group_product(driver, soup, search_soup=soup)
            else:
                return handle_singular_product(soup, search_soup=soup)

        except Exception as e:
            print(f"  Error on attempt {attempt + 1}/{retries} for {code}: {e}")
            time.sleep(2 ** attempt)

    print(f"  ❌ Exhausted retries for {code}")
    return dict(_FAILED_RESULT)


def scrape_with_tab_pool(
    driver,
    handles: list,
    product_urls: list,
    max_final_retries: int = 2,
) -> list:
    """
    Scrape all product URLs using round-robin scheduling across a tab pool.
    Failed products are collected and retried on a single stable tab after
    the main pass, rather than being written as blank rows immediately.

    Args:
        driver:            Selenium WebDriver
        handles:           List of window handles from open_tab_pool()
        product_urls:      List of (url, code) tuples in desired output order
        max_final_retries: How many retry rounds to attempt for failed products

    Returns:
        List[dict] in the same order as product_urls
    """
    results   = {}   # code -> result dict (allows clean overwrite on retry)
    queue     = deque(product_urls)
    tab_index = 0
    total     = len(product_urls)
    processed = 0

    print(f"\n🔄 Round-robin scrape — {len(handles)} tabs, {total} products\n")

    # ── Main pass ─────────────────────────────────────────────────────────────
    while queue:
        url, code = queue.popleft()
        processed += 1

        try:
            driver.switch_to.window(handles[tab_index])
            print(f"[{processed}/{total}] Tab #{tab_index + 1} → {code}")

            result             = retrieve_product_data(driver, url, code)
            result["stockCode"] = code
            results[code]      = result

        except Exception as e:
            print(f"  ❌ Unhandled error for {code}: {e}")
            results[code] = {"stockCode": code, **_FAILED_RESULT}

        tab_index = (tab_index + 1) % len(handles)

    # ── Retry pass ────────────────────────────────────────────────────────────
    failed = [
        (url, code) for url, code in product_urls
        if results.get(code, {}).get("stok_durumu") == FETCH_FAILED
    ]

    if failed:
        print(f"\n🔁 Retry pass: {len(failed)} failed product(s)...")
        driver.switch_to.window(handles[0])

        for round_num in range(1, max_final_retries + 1):
            still_failing = []

            for url, code in failed:
                print(f"  Retry {round_num}/{max_final_retries} → {code}")
                time.sleep(random.uniform(3, 6))

                result             = retrieve_product_data(driver, url, code, retries=2)
                result["stockCode"] = code
                results[code]      = result

                if result.get("stok_durumu") == FETCH_FAILED:
                    still_failing.append((url, code))

            failed = still_failing
            if not failed:
                print("  ✅ All previously failed products resolved.")
                break
            print(f"  ⚠ {len(failed)} still failing after retry round {round_num}")

    if failed:
        print(f"\n⚠ Permanent failures ({len(failed)}):")
        for _, code in failed:
            print(f"   - {code}")

    # Restore original input order
    ordered = [results[code] for _, code in product_urls if code in results]
    print(f"\n✅ Scrape complete — {len(ordered)} products, {len(failed)} permanent failures\n")
    return ordered


def does_product_exist(driver, code: str):
    """
    Check product existence via the search endpoint.

    ⚠ DEPRECATED: No longer called in the main scraping loop (double navigation).
    Kept for use in tests/test.py.

    Returns:
        (exists: bool, soup: BeautifulSoup)
    """
    url = (
        "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY"
        f"/ViewParametricSearch-SimpleOfferSearch?SearchType=all&SearchTerm={code}"
    )
    print(f"  Checking existence of {code} via search...")
    driver.get(url)
    wait_for_element_or_error(driver)

    soup      = BeautifulSoup(driver.page_source, "html.parser")
    error_el  = soup.find("p", class_="headlineStyle4")
    exists    = not (error_el and f"{code} için aramanız başarısız oldu." in error_el.text)
    return exists, soup