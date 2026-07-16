"""
Scrapes every blog post from the DxE "News" page (Blog tab) at
https://www.directactioneverywhere.com/news

The blog listing paginates via client-side JavaScript (Finsweet/Webflow),
so this uses a real headless browser (Playwright) to click through every
page, collect each post's URL, then visits each post individually to pull
its title, date, and full body text.

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
    """Click through every page of the Blog tab, collecting unique post URLs."""
    urls: list[str] = []
    seen = set()

    page.goto(NEWS_URL, wait_until="networkidle")

    # The Blog section's pagination counter looks like "1 / 77", "2 / 77", etc.
    # That "/ 77" fragment is unique to the Blog tab (the other three tabs on
    # this page show "/ 145", "/ 10", and "/ 18"), so anchoring on it — rather
    # than on a /dxe-in-the-news/ link, which also appears in other sections —
    # reliably scopes us to the right container and its real "Next" button.
    counter = page.get_by_text("/ 77", exact=False).first
    counter.wait_for(state="visible", timeout=15000)
    total_pages_text = counter.inner_text()
    total_pages = int(total_pages_text.split("/")[-1].strip())
    print(f"  Blog section reports {total_pages} total pages")

    section = counter.locator(
        "xpath=ancestor::*[self::div or self::section][.//a[contains(@href,'/dxe-in-the-news/')]][1]"
    ).first

    page_num = 1
    while True:
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

        if page_num >= total_pages:
            break

        next_button = section.get_by_text("Next", exact=True)
        if next_button.count() == 0:
            print("  no Next button found — stopping early")
            break

        try:
            next_button.first.click()
            # Wait for the counter to actually advance before scraping again,
            # rather than guessing with a fixed delay.
            page.wait_for_function(
                """([expectedPrefix, totalSuffix]) => {
                    const els = [...document.querySelectorAll('*')].filter(
                        el => el.children.length === 0 && el.textContent.includes(totalSuffix)
                    );
                    return els.some(el => el.textContent.trim().startsWith(expectedPrefix));
                }""",
                arg=[f"{page_num + 1} /", f"/ {total_pages}"],
                timeout=10000,
            )
        except Exception as e:
            print(f"  stopping: couldn't advance past page {page_num} ({e})")
            break

        page_num += 1
        if page_num > 200:  # safety valve
            break

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
