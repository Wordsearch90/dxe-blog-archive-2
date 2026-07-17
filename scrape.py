"""
Scrapes every blog post from the DxE "News" page (Blog tab) at
https://www.directactioneverywhere.com/news

The blog listing paginates via a URL query param (?f09b7e50_page=N) that's
read by client-side JS (Finsweet/Webflow) on load, so this uses a real
headless browser (Playwright) — navigating directly to each page's URL,
verifying it actually rendered the right page — to collect every post URL,
then visits each post individually to pull its title, date, and full body
text.

Output: docs/posts.json — consumed by docs/index.html (the search page).
"""

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

NEWS_URL = "https://www.directactioneverywhere.com/news"
OUTPUT_PATH = Path(__file__).parent / "docs" / "posts.json"
FOOTER_MARKER = "Until every animal is free"


def collect_blog_post_urls(page) -> list[str]:
    """Visit each ?f09b7e50_page=N URL directly, collecting unique post URLs.

    The Blog tab's pagination is client-side JS (Finsweet/Webflow), and its
    "Next" links point to URLs like ?f09b7e50_page=2, ?f09b7e50_page=3, etc.
    A real browser (unlike a plain HTTP fetch) executes that JS on load and
    reads the URL to render the right page directly — so instead of clicking
    "Next" repeatedly, we can just navigate straight to each page number.
    """
    urls: list[str] = []
    seen = set()

    def get_counter(page):
        # Webflow's built-in ".w-page-count" a11y element, e.g.
        # aria-label="Page 3 of 77". It's visually hidden by design, so we
        # read its attribute/text directly rather than waiting for visibility.
        counter = page.get_by_text("/ 77", exact=False).first
        counter.wait_for(state="attached", timeout=15000)
        return counter

    # First, load page 1 to discover the real total page count.
    page.goto(NEWS_URL, wait_until="networkidle")
    counter = get_counter(page)
    aria_label = counter.get_attribute("aria-label") or ""
    match = re.search(r"of (\d+)", aria_label)
    total_pages = int(match.group(1)) if match else int(counter.text_content().split("/")[-1].strip())
    print(f"  Blog section reports {total_pages} total pages")

    for page_num in range(1, total_pages + 1):
        url = f"{NEWS_URL}?f09b7e50_page={page_num}"
        page.goto(url, wait_until="networkidle")

        # Confirm the page actually advanced to the number we asked for.
        # If not (this site's CDN has occasionally served a stale/cached
        # page for a given query param), force a hard reload and recheck
        # once before giving up on this page.
        counter = get_counter(page)
        expected = f"Page {page_num} of"
        actual = counter.get_attribute("aria-label") or ""
        if not actual.startswith(expected):
            print(f"  page {page_num}: got '{actual}', forcing reload and retrying...")
            page.reload(wait_until="networkidle")
            counter = get_counter(page)
            actual = counter.get_attribute("aria-label") or ""
            if not actual.startswith(expected):
                print(f"  page {page_num}: still showing '{actual}' after retry — skipping this page")
                continue

        section = counter.locator(
            "xpath=ancestor::*[self::div or self::section][.//a[contains(@href,'/dxe-in-the-news/')]][1]"
        ).first
        links = section.locator("a[href*='/dxe-in-the-news/']")
        count = links.count()
        for i in range(count):
            href = links.nth(i).get_attribute("href")
            if href and href not in seen:
                seen.add(href)
                if href.startswith("/"):
                    href = "https://www.directactioneverywhere.com" + href
                urls.append(href)

        print(f"  page {page_num}/{total_pages}: {len(urls)} unique posts so far")

    return urls


def scrape_post(page, url: str) -> dict:
    page.goto(url, wait_until="networkidle")
    full_text = page.inner_text("body")

    # Title: first non-empty line after nav, or the <h1>.
    title = ""
    try:
        title = page.locator("h1").first.inner_text().strip()
    except Exception:
        pass

    # Trim boilerplate: keep everything from the title to the footer marker.
    body = full_text
    if title and title in body:
        body = body.split(title, 1)[1]
    if FOOTER_MARKER in body:
        body = body.split(FOOTER_MARKER, 1)[0]
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # Best-effort date extraction: the publish date reliably appears within
    # the first ~150 characters right after the title (before the byline
    # image caption and article body, which may mention unrelated dates).
    date_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}",
        body[:150],
    )
    date = date_match.group(0) if date_match else ""

    return {
        "title": title,
        "date": date,
        "url": url,
        "body": body,
    }


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        print("Collecting blog post URLs (paginating through Blog tab)...")
        urls = collect_blog_post_urls(page)
        print(f"Found {len(urls)} total blog posts.")

        posts = []
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Scraping {url}")
            try:
                posts.append(scrape_post(page, url))
            except Exception as e:
                print(f"  FAILED: {e}")
            time.sleep(0.5)

        browser.close()

    OUTPUT_PATH.write_text(json.dumps(posts, indent=2, ensure_ascii=False))
    print(f"Saved {len(posts)} posts to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
