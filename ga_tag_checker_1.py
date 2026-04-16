import re
import time
import random
import json
import logging

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# -----------------------------
# LOGGING
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# -----------------------------
# CONSTANTS
# -----------------------------
# GA4 uses negative lookbehind to avoid false positives on GTM IDs
GTM_PATTERN = r"GTM-[A-Z0-9]+"
GA4_PATTERN = r"(?<![A-Z])G-[A-Z0-9]+"
UA_PATTERN  = r"UA-\d+-\d+"

GTM_NETWORK_KEYWORDS = [
    "googletagmanager.com",
    "google-analytics.com",
    "gtag/js",
    "gtm.js",
    "analytics.js",
    "collect?v=",
    "collect?v=2",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119 Safari/537.36",
]

URLS = [
    "https://almaapartments.com/",
    "https://www.bainbridgeinternationalapts.com/",
    "https://www.virtuonbagbyave.com/",
]


# -----------------------------
# DRIVER
# -----------------------------
def create_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )

    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return driver


# -----------------------------
# PAGE INTERACTION
# -----------------------------
def simulate_human(driver: webdriver.Chrome) -> None:
    """Scroll, move the mouse, then wait for async tags to fire."""
    time.sleep(random.uniform(2, 5))

    scroll_height = driver.execute_script("return document.body.scrollHeight")
    for i in range(1, 5):
        driver.execute_script(f"window.scrollTo(0, {scroll_height * i / 5});")
        time.sleep(random.uniform(1, 2))

    driver.execute_script("""
        document.dispatchEvent(new MouseEvent('mousemove', {
            view: window, bubbles: true, cancelable: true,
            clientX: Math.random() * window.innerWidth,
            clientY: Math.random() * window.innerHeight
        }));
    """)

    logger.info("Waiting for async tags to fire post-scroll...")
    time.sleep(random.uniform(3, 5))


def load_page(driver: webdriver.Chrome, url: str) -> None:
    driver.get(url)
    time.sleep(random.uniform(3, 6))
    simulate_human(driver)


# -----------------------------
# EXTRACTION
# -----------------------------
def extract_tags(text: str) -> dict[str, list[str]]:
    return {
        "GTM": list(set(re.findall(GTM_PATTERN, text))),
        "GA4": list(set(re.findall(GA4_PATTERN, text))),
        "UA":  list(set(re.findall(UA_PATTERN, text))),
    }


def extract_scripts(driver: webdriver.Chrome) -> str:
    return " ".join(
        (s.get_attribute("innerHTML") or "") + " " + (s.get_attribute("src") or "")
        for s in driver.find_elements("tag name", "script")
    )


def extract_iframes(driver: webdriver.Chrome) -> str:
    """Capture GTM noscript fallback iframes (e.g. googletagmanager.com/ns.html)."""
    iframes = driver.find_elements("tag name", "iframe")
    logger.info(f"Found {len(iframes)} iframe(s).")
    return " ".join(iframe.get_attribute("src") or "" for iframe in iframes)


def extract_network(driver: webdriver.Chrome) -> str:
    """Return a space-joined string of GTM/GA-relevant network request URLs."""
    relevant_urls = []
    for entry in driver.get_log("performance"):
        try:
            log = json.loads(entry["message"])["message"]
            if log["method"] == "Network.requestWillBeSent":
                url = log["params"]["request"]["url"]
                if any(kw in url for kw in GTM_NETWORK_KEYWORDS):
                    relevant_urls.append(url)
        except (KeyError, json.JSONDecodeError) as e:
            logger.debug(f"Log parse error (skipping): {e}")
    return " ".join(relevant_urls)


def extract_datalayer(driver: webdriver.Chrome) -> str:
    """Read window.dataLayer to catch IDs pushed dynamically at runtime."""
    try:
        result = driver.execute_script("return JSON.stringify(window.dataLayer || [])")
        if result:
            logger.info("Successfully read window.dataLayer.")
            return result
    except Exception as e:
        logger.warning(f"Could not read window.dataLayer: {e}")
    return ""


# -----------------------------
# MAIN CHECKER
# -----------------------------
def check_sites(urls: list[str]) -> dict[str, dict[str, list[str]]]:
    driver = create_driver()
    results = {}

    try:
        for url in urls:
            logger.info(f"Checking: {url}")
            load_page(driver, url)

            combined = " ".join([
                driver.page_source,
                extract_scripts(driver),
                extract_iframes(driver),
                extract_network(driver),
                extract_datalayer(driver),
            ])

            tags = extract_tags(combined)
            results[url] = tags
            logger.info(f"Done: {url} → {tags}")
    finally:
        driver.quit()

    return results


# -----------------------------
# ENTRY POINT
# -----------------------------
def print_results(results: dict[str, dict[str, list[str]]]) -> None:
    print("\n===== RESULTS =====")
    for site, tags in results.items():
        print(f"\n{site}")
        for tag_type, ids in tags.items():
            print(f"  {tag_type}: {', '.join(ids) if ids else 'None'}")


if __name__ == "__main__":
    results = check_sites(URLS)
    print_results(results)
