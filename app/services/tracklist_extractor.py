from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/125.0.0.0 Safari/537.36",
    # Chrome en macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/125.0.0.0 Safari/537.36",
    # Edge en Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/125.0.0.0 Safari/537.36 " "Edg/125.0.0.0",
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
class TracklistDetail:
    title: str
    url: str
    date: Optional[str] = None
    event: Optional[str] = None
    venue: Optional[str] = None
    city: Optional[str] = None
    songs: List["SongEntry"] = field(default_factory=list)


@dataclass
class DJResult:
    id: str
    name: str
    tracklists: List[TracklistDetail]
    error: Optional[str] = None


@dataclass
class SongEntry:
    artist: str
    title: str
    label: str
    position: Optional[int] = None
    timecode: Optional[str] = None
    beatport_url: Optional[str] = None


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


def _scrape_items_for_dj(driver: webdriver.Chrome, dj_id: str, *, timeout: float) -> List[TracklistEntry]:
    url = f"{BASE_URL}/dj/{dj_id}/index.html"
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.bItm.oItm, div.bTitle")))
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


def _scrape_songs_from_tracklist(driver: webdriver.Chrome, url: str, *, timeout: float) -> TracklistDetail:
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tlTab, div.bCont.tl, meta[property='og:title']")))
    except Exception:
        pass

    html = driver.page_source
    if _is_captcha(html):
        raise RuntimeError("CAPTCHA detected or anti-bot page (tracklist)")

    # Title of the tracklist
    tl_title = None
    try:
        meta = driver.find_element(By.CSS_SELECTOR, "meta[property='og:title']")
        tl_title = (meta.get_attribute("content") or "").strip()
    except Exception:
        tl_title = driver.title or url

    # Metadata: date, event, venue, city
    date_text: Optional[str] = None
    event_text: Optional[str] = None
    venue_text: Optional[str] = None
    city_text: Optional[str] = None

    # Try structured metadata for date
    try:
        date_meta = driver.find_element(By.CSS_SELECTOR, 'meta[itemprop="startDate"]')
        date_text = (date_meta.get_attribute("content") or "").strip() or None
    except Exception:
        # Newer layout: TL date lives inside a summary tab with pairs of labels/values
        # Example block:
        # <div class="sTab c2 cM">
        #   <div title="tracklist recording date">TL date</div>
        #   <div>Sat, Aug 30 2025</div>
        #   ...
        # </div>
        try:
            # First, try adjacent sibling to the label with the specific title
            tl_date_vals = driver.find_elements(
                By.CSS_SELECTOR,
                "div.sTab.c2.cM div[title='tracklist recording date'] + div",
            )
            if tl_date_vals:
                date_text = (tl_date_vals[0].text or "").strip() or None
        except Exception:
            pass
        if not date_text:
            # Fallback: iterate the children of the summary tab and pick value after 'TL date'
            try:
                tab = driver.find_element(By.CSS_SELECTOR, "div.sTab.c2.cM")
                children = tab.find_elements(By.XPATH, "./div")
                for i, el in enumerate(children):
                    label_txt = ((el.get_attribute("title") or el.text) or "").strip().lower()
                    if label_txt in (
                        "tracklist recording date",
                        "tl date",
                        "tracklist date",
                    ):
                        if i + 1 < len(children):
                            date_text = (children[i + 1].text or "").strip() or None
                            break
            except Exception:
                pass
        if not date_text:
            # Last resort: regex over raw HTML looking for the TL date label/value pair
            m = re.search(
                r"<div[^>]*title=\"tracklist recording date\"[^>]*>.*?</div>\s*<div>\s*([^<]+?)\s*</div>",
                html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if m:
                date_text = m.group(1).strip()
        if not date_text:
            # Very last fallback: look for itemprop time element if present
            try:
                time_el = driver.find_element(By.CSS_SELECTOR, 'time[itemprop="startDate"]')
                date_text = (time_el.get_attribute("datetime") or time_el.text or "").strip() or None
            except Exception:
                m2 = re.search(r"itemprop=\"startDate\"[^>]*content=\"([^\"]+)\"", html)
                if m2:
                    date_text = m2.group(1).strip()

    # Links for event/venue/city
    try:
        ev = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/event/"]')
        if ev:
            event_text = (ev[0].text or "").strip() or None
    except Exception:
        pass
    try:
        ve = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/venue/"]')
        if ve:
            venue_text = (ve[0].text or "").strip() or None
    except Exception:
        pass
    try:
        ci = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/city/"]')
        if ci:
            city_text = (ci[0].text or "").strip() or None
    except Exception:
        pass

    # Extract track rows
    songs: List[SongEntry] = []
    # Parent containers hold position and Beatport; child 'div.bCont.tl' holds artist/title
    pairs: List[tuple] = []  # (container, info_row)
    try:
        containers = driver.find_elements(By.CSS_SELECTOR, "div[id*='tlp']")
        for cont in containers:
            try:
                info_row = cont.find_element(By.CSS_SELECTOR, "div.bCont.tl")
                pairs.append((cont, info_row))
            except Exception:
                continue
    except Exception:
        containers = []
    if not pairs:
        # Fallback to older approach
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "div.bCont.tl")
            pairs = [(row, row) for row in rows]
        except Exception:
            pairs = []

    for container, row in pairs:
        try:
            # ver el valor de row
            roval = (row.get_attribute("outerHTML") or "").strip()
            print(f"Row HTML: {roval[:200]}...")  # Debug output, limit length
            # Position: look specifically inside the bPlay block within the row.
            # Also detect special non-numeric markers like 'W/' indicating a mashup line.
            pos_val: Optional[int] = None
            mashup_with_prev: bool = False
            try:
                # First, try the current layout: the play/position area
                bplay = None
                try:
                    bplay = container.find_element(By.CSS_SELECTOR, "div.bPlay")
                except Exception:
                    bplay = None
                if bplay is not None:
                    for c in bplay.find_elements(By.CSS_SELECTOR, "span"):
                        txt = (c.text or "").strip()
                        if not txt:
                            continue
                        if re.search(r"(?i)\bw\s*/", txt):
                            mashup_with_prev = True
                        mpos = re.search(r"(\d{1,3})", txt)
                        if mpos:
                            pos_val = int(mpos.group(1))
                            break
                # If no numeric pos found and not explicitly a mashup from bPlay,
                # fall back to older selectors or textual prefixes within the row
                if pos_val is None and not mashup_with_prev:
                    for c in container.find_elements(
                        By.CSS_SELECTOR,
                        'span[id*="tlp"], span.tlNum, span.ptNum, div.bPos, div.tlRow__pos, div.bTL__nr',
                    ):
                        txt = (c.text or "").strip()
                        mpos = re.match(r"^(\d{1,3})\.?$", txt) or re.search(r"(\d{1,3})", txt)
                        if mpos:
                            pos_val = int(mpos.group(1))
                            break
                if pos_val is None and not mashup_with_prev:
                    mpos2 = re.match(r"\s*(\d{1,3})[\.:]\s", (container.text or row.text))
                    if mpos2:
                        pos_val = int(mpos2.group(1))
            except Exception:
                pos_val = None

            # Timecode via div[id*="cue"]
            timecode_val: Optional[str] = None
            try:
                # Prefer container, then fallback to row
                scopes = [container, row]
                for scope in scopes:
                    try:
                        for c in scope.find_elements(By.CSS_SELECTOR, 'div[id*="cue"]'):
                            txt = (c.text or "").strip()
                            mtime = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", txt)
                            if mtime:
                                timecode_val = mtime.group(1)
                                break
                        if timecode_val:
                            break
                    except Exception:
                        continue
                if not timecode_val:
                    # fallback: try known time span classes
                    for selector in ["span.tTime", "span.time", "span.tlTime"]:
                        els = container.find_elements(By.CSS_SELECTOR, selector) or row.find_elements(By.CSS_SELECTOR, selector)
                        if els:
                            ttxt = (els[0].text or "").strip()
                            if ttxt:
                                timecode_val = ttxt
                                break
                    if not timecode_val:
                        mtime = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", (container.text or row.text))
                        if mtime:
                            timecode_val = mtime.group(1)
            except Exception:
                timecode_val = None

            name_val = ""
            try:
                name_meta = row.find_element(By.CSS_SELECTOR, 'meta[itemprop="name"]')
                name_val = (name_meta.get_attribute("content") or "").strip()
            except Exception:
                # Fallback: try span with itemprop name
                try:
                    name_span = row.find_element(By.CSS_SELECTOR, 'span[itemprop="name"]')
                    name_val = (name_span.text or "").strip()
                except Exception:
                    name_val = ""

            # Try to get artists from semantic elements first
            artist_parts: List[str] = []
            try:
                artist_els = row.find_elements(By.CSS_SELECTOR, 'a[itemprop="byArtist"], span[itemprop="byArtist"]')
                for el in artist_els:
                    txt = (el.text or "").strip()
                    if txt:
                        artist_parts.append(txt)
            except Exception:
                pass
            # Deduplicate preserving order
            seen = set()
            artist_parts_unique = []
            for a in artist_parts:
                if a not in seen:
                    seen.add(a)
                    artist_parts_unique.append(a)

            label_text = ""
            try:
                pub_el = row.find_element(By.CSS_SELECTOR, 'meta[itemprop="publisher"]')
                pub_html = (pub_el.get_attribute("content") or "").strip()
                pub_text = re.sub(r"<[^>]+>", "", pub_html).strip()
                # remove surrounding brackets if present
                pub_text = re.sub(r"^[\[\(\{\s]+|[\]\)\}\s]+$", "", pub_text)
                label_text = pub_text
            except Exception:
                label_text = ""
            if not label_text and name_val:
                m = re.search(r"\[(.*?)\]\s*$", name_val)
                if m:
                    label_text = m.group(1).strip()

            # Heuristics to split artist and title
            artist_joined = ", ".join(artist_parts_unique)
            title_candidate = name_val
            # If the name contains a label suffix like ' [Label]',
            # strip it (we captured label above)
            title_candidate = re.sub(r"\s*\[.*?\]\s*$", "", title_candidate).strip()
            if not artist_joined and " - " in title_candidate:
                # Split at first hyphen occurrence
                parts = title_candidate.split(" - ", 1)
                artist_joined = parts[0].strip()
                title_candidate = parts[1].strip() if len(parts) > 1 else title_candidate
            else:
                # If the title starts with '<artist> - ', strip prefix
                for prefix in ([artist_joined] + artist_parts_unique) if artist_joined else []:
                    if prefix and title_candidate.startswith(prefix + " - "):
                        title_candidate = title_candidate[len(prefix) + 3 :].strip()
                        break

            # Beatport link: click shopping cart in parent container to reveal embed, then read link
            beatport_url: Optional[str] = None
            try:
                icon = None
                try:
                    icon = container.find_element(By.CSS_SELECTOR, "i.fa-shopping-cart")
                except Exception:
                    try:
                        icon = row.find_element(By.CSS_SELECTOR, "i.fa-shopping-cart")
                    except Exception:
                        icon = None
                clickable = None
                try:
                    clickable = icon.find_element(By.XPATH, "./ancestor::*[self::a or self::button][1]")
                except Exception:
                    clickable = icon
                try:
                    driver.execute_script('arguments[0].scrollIntoView({block:"center"});', clickable)
                except Exception:
                    pass
                try:
                    clickable.click()
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", clickable)
                    except Exception:
                        pass
                # Wait briefly for embed to appear within row or globally
                end_ts = time.time() + 2.5
                while time.time() < end_ts and not beatport_url:
                    embeds = row.find_elements(By.CSS_SELECTOR, "div.beatport-embed")
                    if not embeds:
                        embeds = driver.find_elements(By.CSS_SELECTOR, "div.beatport-embed")
                    found = None
                    for emb in embeds:
                        if emb.is_displayed():
                            found = emb
                            break
                    if found is not None:
                        # Link in anchor or iframe
                        link = None
                        try:
                            link = found.find_element(By.CSS_SELECTOR, 'a[href*="beatport.com"]')
                            beatport_url = (link.get_attribute("href") or "").strip() or None
                        except Exception:
                            try:
                                iframe = found.find_element(By.CSS_SELECTOR, 'iframe[src*="beatport"]')
                                beatport_url = (iframe.get_attribute("src") or "").strip() or None
                            except Exception:
                                pass
                        if beatport_url:
                            break
                    if not beatport_url:
                        time.sleep(0.15)
            except Exception:
                beatport_url = None

            artist_final = artist_joined
            title_final = title_candidate

            # If this row is a mashup indicator (W/), merge with previous song instead of adding a new one
            if mashup_with_prev and songs:
                prev = songs[-1]
                # Merge artists, avoiding duplicates and empty parts
                prev_artists = [p.strip() for p in re.split(r"\s*[,&xX\+]+\s*", prev.artist) if p.strip()] if prev.artist else []
                cur_artists = [p.strip() for p in re.split(r"\s*[,&xX\+]+\s*", artist_final) if p.strip()] if artist_final else []
                combined_artists: List[str] = []
                for a in prev_artists + cur_artists:
                    if a and a not in combined_artists:
                        combined_artists.append(a)
                if combined_artists:
                    prev.artist = " & ".join(combined_artists)

                # Merge titles using ' W/ ' to reflect the mashup
                if prev.title and title_final:
                    prev.title = f"{prev.title} W/ {title_final}"
                elif title_final and not prev.title:
                    prev.title = title_final
                # Keep previous label/position/time/beatport
                # Skip appending a new entry for mashup continuation
                continue
            # As a last resort, if both empty, skip
            if not title_final and not artist_final:
                continue
            songs.append(
                SongEntry(
                    artist=artist_final,
                    title=title_final,
                    label=label_text,
                    position=pos_val,
                    timecode=timecode_val,
                    beatport_url=beatport_url,
                )
            )
        except Exception:
            continue

    return TracklistDetail(
        title=tl_title or url,
        url=url,
        date=date_text,
        event=event_text,
        venue=venue_text,
        city=city_text,
        songs=songs,
    )


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

                # For each selected tracklist, fetch its songs
                details: List[TracklistDetail] = []
                for entry in filtered:
                    try:
                        detail = _scrape_songs_from_tracklist(driver, entry.url, timeout=options.timeout)
                        if not detail.title:
                            detail.title = entry.title
                        details.append(detail)
                        time.sleep(random.uniform(options.delay_min, options.delay_max))
                    except Exception as sub_e:  # noqa: BLE001
                        details.append(
                            TracklistDetail(
                                title=entry.title,
                                url=entry.url,
                                date=None,
                                event=None,
                                venue=None,
                                city=None,
                                songs=[SongEntry(artist="", title=f"ERROR: {sub_e}", label="")],
                            )
                        )

                results.append(DJResult(id=dj.id, name=dj.name, tracklists=details))
            except Exception as e:  # noqa: BLE001
                results.append(DJResult(id=dj.id, name=dj.name, tracklists=[], error=str(e)))
        # Persist updated config (with refreshed last_title per DJ)
        try:
            config_path.write_text(json.dumps(raw_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
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
    "SongEntry",
    "TracklistDetail",
    "scrape_all_from_config",
]
