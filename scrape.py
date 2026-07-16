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

    # Find the "DxE's Blog" section heading, then work within its container.
    heading = page.get_by_text("DxE's Blog", exact=False).first
    section = heading.locator(
        "xpath=ancestor::div[.//a[contains(@href,'/dxe-in-the-news/')]][1]"
    ).first

    page_num = 1
    while True:
        # Collect links visible in this section right now.
        links = section.locator("a[href*='/dxe-in-the-news/']")
        count = links.count()
        for i in range(count):
            href = links.nth(i).get_attribute("href")
            if href and href not in seen:
                seen.add(href)
                if href.startswith("/"):
                    href = "https://www.directactioneverywhere.com" + href
                urls.append(href)

        print(f"  page {page_num}: {len(urls)} unique posts so far")

        next_button = section.get_by_text("Next", exact=True)
        if next_button.count() == 0:
            break
        try:
            next_button.first.click()
            page.wait_for_timeout(1200)  # let the JS render the new page
        except Exception as e:
            print(f"  stopping: couldn't click Next ({e})")
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

    # Best-effort date extraction: look for a "Month DD, YYYY" pattern near the top.
    date_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}",
        body,
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
