from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://www.1001tracklists.com"


USER_AGENTS = [
    # Chrome en Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    # Chrome en macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    # Edge en Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36 "
    "Edg/125.0.0.0",
]


@dataclass
class DJConfig:
    id: str
    name: str


@dataclass
class ScrapeOptions:
    headless: bool = True
    timeout: float = 20.0
    delay_min: float = 0.5
    delay_max: float = 1.5
    proxy: Optional[str] = None
    cookies: Dict[str, str] | None = None
    user_agent: Optional[str] = None


@dataclass
class TracklistEntry:
    title: str
    url: str


@dataclass
class DJResult:
    id: str
    name: str
    tracklists: List[TracklistEntry]
    error: Optional[str] = None


def _load_config(path: Path) -> tuple[List[DJConfig], ScrapeOptions, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    djs_raw = data.get("djs", [])
    djs: List[DJConfig] = []
    for item in djs_raw:
        dj_id = (item.get("id") or item.get("slug") or "").strip()
        name = (item.get("name") or dj_id).strip()
        if dj_id:
            djs.append(DJConfig(id=dj_id, name=name))

    scrape_raw = data.get("scrape", {}) or {}
    delay = scrape_raw.get("delay_seconds", [0.5, 1.5])
    if not isinstance(delay, (list, tuple)) or len(delay) != 2:
        delay = [0.5, 1.5]
    options = ScrapeOptions(
        headless=bool(scrape_raw.get("headless", True)),
        timeout=float(scrape_raw.get("timeout", 20.0) or 20.0),
        delay_min=float(delay[0]),
        delay_max=float(delay[1]),
        proxy=(scrape_raw.get("proxy") or None),
        cookies=scrape_raw.get("cookies") or None,
        user_agent=(scrape_raw.get("user_agent") or None),
    )
    return djs, options, data


def _is_captcha(content: str) -> bool:
    lowered = content.lower()
    indicators = [
        "captcha",
        "are you human",
        "verify you are human",
        "security check",
        "cf-chl-",
        "cf-error",
        "just a moment",
        "g-recaptcha",
        "h-captcha",
    ]
    return any(tok in lowered for tok in indicators)


def _build_chrome(options: ScrapeOptions) -> webdriver.Chrome:
    ua = options.user_agent or random.choice(USER_AGENTS)
    chrome_options = Options()
    if options.headless:
        # Use new headless mode for Chromium which is less detectable
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"--user-agent={ua}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    prefs = {"intl.accept_languages": "es-ES,es;q=0.9,en;q=0.8"}
    chrome_options.add_experimental_option("prefs", prefs)
    if options.proxy:
        chrome_options.add_argument(f"--proxy-server={options.proxy}")

    driver = webdriver.Chrome(options=chrome_options)
    # Stealth tweaks via CDP
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['es-ES', 'es', 'en']});
                """,
            },
        )
        # Also set UA via network override for consistency
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": ua})
    except Exception:
        # Best-effort; not critical if this fails
        pass
    return driver


def _apply_cookies(driver: webdriver.Chrome, cookies: Dict[str, str]) -> None:
    if not cookies:
        return
    # Must be on domain before adding cookies
    driver.get(BASE_URL + "/")
    time.sleep(0.3)
    for name, value in cookies.items():
        try:
            driver.add_cookie(
                {
                    "name": name,
                    "value": value,
                    "domain": "www.1001tracklists.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                }
            )
        except Exception:
            # Ignore cookie failures to avoid breaking entire run
            pass


def _scrape_items_for_dj(
    driver: webdriver.Chrome, dj_id: str, *, timeout: float
) -> List[TracklistEntry]:
    url = f"{BASE_URL}/dj/{dj_id}/index.html"
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.bItm.oItm, div.bTitle"))
        )
    except Exception:
        # Continue; we'll still try to parse whatever loaded
        pass

    html = driver.page_source
    if _is_captcha(html):
        raise RuntimeError("CAPTCHA detected or anti-bot page")

    results: List[TracklistEntry] = []
    # Prefer precise selector for items
    items = driver.find_elements(By.CSS_SELECTOR, "div.bItm.oItm")
    for itm in items:
        try:
            title_el = itm.find_element(By.CSS_SELECTOR, "div.bTitle")
            text = title_el.text.strip()
            href: Optional[str] = None
            # Try to extract from onclick attribute
            onclick = itm.get_attribute("onclick") or ""
            m = re.search(r"window\.open\(['\"](.*?)['\"],", onclick)
            if m:
                href = m.group(1)
            if not href:
                # Fallback to anchor with href
                try:
                    a = itm.find_element(By.CSS_SELECTOR, "a[href]")
                    href = a.get_attribute("href")
                except Exception:
                    href = None
            if href and href.startswith("/"):
                href = BASE_URL + href
            if text and href:
                results.append(TracklistEntry(title=text, url=href))
        except Exception:
            continue

    # Fallbacks if structure changes
    if not results:
        els = driver.find_elements(By.CSS_SELECTOR, "a.bItm__title, a.tlTitle, div.bTitle")
        for el in els:
            text = el.text.strip()
            href = None
            try:
                href = el.get_attribute("href")
            except Exception:
                href = None
            if href and href.startswith("/"):
                href = BASE_URL + href
            if text and href:
                results.append(TracklistEntry(title=text, url=href))
    return results


def scrape_all_from_config(config_path: Path, *, limit: Optional[int] = None) -> List[DJResult]:
    djs, options, raw_cfg = _load_config(config_path)
    if not djs:
        return []

    driver = _build_chrome(options)
    try:
        if options.cookies:
            _apply_cookies(driver, options.cookies)

        results: List[DJResult] = []
        # Build quick lookup to update config
        dj_objs: List[dict] = list(raw_cfg.get("djs", []))
        id_to_obj = {(obj.get("id") or obj.get("slug")): obj for obj in dj_objs}

        for dj in djs:
            # Jitter to look more human
            time.sleep(random.uniform(options.delay_min, options.delay_max))
            try:
                items = _scrape_items_for_dj(driver, dj.id, timeout=options.timeout)
                # Filter by last_title unless 'limit' is provided (ignore last when limiting)
                last_title: Optional[str] = None
                src_obj = id_to_obj.get(dj.id)
                if src_obj:
                    last_title = src_obj.get("last_title")

                if limit is not None:
                    filtered = items[: max(0, int(limit))]
                else:
                    filtered: List[TracklistEntry] = []
                    if last_title:
                        for entry in items:
                            if entry.title == last_title:
                                break
                            filtered.append(entry)
                    else:
                        filtered = items

                # Update last_title to the current first (if any)
                new_last = items[0].title if items else last_title
                if src_obj is not None and new_last:
                    src_obj["last_title"] = new_last

                results.append(DJResult(id=dj.id, name=dj.name, tracklists=filtered))
            except Exception as e:  # noqa: BLE001
                results.append(DJResult(id=dj.id, name=dj.name, tracklists=[], error=str(e)))
        # Persist updated config (with refreshed last_title per DJ)
        try:
            config_path.write_text(
                json.dumps(raw_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            # Non-fatal if we fail to persist
            pass
        return results
    finally:
        try:
            driver.quit()
        except Exception:
            pass


__all__ = [
    "DJConfig",
    "ScrapeOptions",
    "DJResult",
    "scrape_all_from_config",
]
