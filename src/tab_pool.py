"""
tab_pool.py
-----------
Responsible for:
- Creating a pool of browser tabs
- Injecting authenticated cookies into each tab
"""

import time
from src.page_loader import wait_for_page_ready


def apply_cookies_to_tab(driver, base_url="https://www.hafele.com.tr/", cookies=None):
    """
    Navigate to base_url and inject all cookies into the current tab.

    Args:
        driver:   Selenium WebDriver
        base_url: Must be the same domain as the cookies
        cookies:  List of cookie dicts from driver.get_cookies()

    Raises:
        Exception if navigation or cookie injection fails
    """
    if cookies is None:
        cookies = []

    print(f"  Navigating to {base_url} to inject cookies...")
    driver.get(base_url)
    wait_for_page_ready(driver)

    for cookie in cookies:
        try:
            c = cookie.copy()
            # Remove keys Selenium does not accept
            for key in ["sameSite", "domain"]:
                c.pop(key, None)
            driver.add_cookie(c)
            print(f"  ✓ Added cookie: {c.get('name', 'unknown')}")
        except Exception as e:
            print(f"  ⚠ Failed to add cookie '{cookie.get('name', 'unknown')}': {e}")

    time.sleep(0.5)
    driver.refresh()
    wait_for_page_ready(driver)
    print("  ✓ Cookies injected and page refreshed")


def open_tab_pool(driver, n_tabs=5, base_url="https://www.hafele.com.tr/", cookies=None):
    """
    Open exactly n_tabs and inject cookies into each one.

    Args:
        driver:   Selenium WebDriver
        n_tabs:   Number of tabs to open (default 5)
        base_url: Domain URL used for cookie injection
        cookies:  List of cookie dicts from driver.get_cookies()

    Returns:
        List[str]: Window handles for each tab (length == n_tabs)

    Raises:
        Exception if tab creation or cookie injection fails
    """
    if cookies is None:
        cookies = []

    handles = []
    print(f"\n📑 Opening tab pool with {n_tabs} tabs...")

    try:
        # First tab: already open, just inject cookies
        print("\nTab 1 (current):")
        apply_cookies_to_tab(driver, base_url, cookies)
        handles.append(driver.current_window_handle)

        # Remaining tabs: open new, switch to it, inject cookies
        for i in range(1, n_tabs):
            print(f"\nTab {i + 1} (new):")
            driver.execute_script("window.open('');")
            time.sleep(1)
            driver.switch_to.window(driver.window_handles[-1])
            apply_cookies_to_tab(driver, base_url, cookies)
            handles.append(driver.current_window_handle)

        print(f"\n✅ Tab pool ready — {len(handles)} tabs\n")
        return handles

    except Exception as e:
        print(f"\n❌ Error creating tab pool: {e}")
        raise