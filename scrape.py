"""
Scrapes every blog post from the DxE "News" page (Blog tab) at
https://www.directactioneverywhere.com/news

The blog listing paginates via a Webflow-native widget whose "Next" button
re-renders the list client-side. This uses a real headless browser
(Playwright) to click through every page, collecting every post's URL, then
visits each post individually to pull its title, date, and full body text.

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
    """Click through the Blog tab's pagination, collecting unique post URLs.

    Direct URL navigation (?f09b7e50_page=N) turned out to be unreliable:
    this site's CDN appears to cache the first page variant it sees and
    then serve that same cached response for other page numbers too. But
    clicking "Next" on this Webflow-native pagination widget re-renders
    the list client-side without a fresh page-level HTTP request, so it
    sidesteps that caching bug entirely.
    """
    urls: list[str] = []
    seen = set()

    page.goto(NEWS_URL, wait_until="networkidle")

    # This page has 4 tabs (All / Top Press / Blog / Press Releases), and
    # each tab's content — including its Next button — is hidden until that
    # tab is activated. Reading the counter's aria-label worked fine while
    # hidden (attribute reads don't require visibility), but clicking the
    # Next button does, which is what caused the previous failure. Click
    # the "Blog" tab first to reveal its section.
    blog_tab = page.get_by_text("Blog", exact=True).first
    blog_tab.click()
    page.wait_for_timeout(500)  # let the tab-switch animation/render settle
    
    # Find the Blog tab's counter specifically. There are 4 ".w-page-count"
    # widgets on this page (All News, Top Press, Blog, Press Releases), so
    # we can't just take .first of that class — instead match on its text,
    # which reliably identifies the Blog one (e.g. "1 / 77", vs "1 / 145",
    # "1 / 10", "1 / 18" for the others). Confirmed via aria-label
    # "Page 1 of 77" in earlier testing. It's visually hidden by design
    # (a11y-only), so we read its attribute directly rather than waiting
    # for visibility.
    counter = page.get_by_text("/ 77", exact=False).first
    counter.wait_for(state="attached", timeout=15000)
    aria_label = counter.get_attribute("aria-label") or ""
    match = re.search(r"of (\d+)", aria_label)
    if not match:
        raise RuntimeError(f"Couldn't parse total page count from '{aria_label}'")
    total_pages = int(match.group(1))
    print(f"  Blog section reports {total_pages} total pages")

    # The pagination wrapper (containing the counter and the Next/Previous
    # buttons) is a nearby ancestor of the counter. Climb up until we find
    # one that also contains a "Next" text element.
    wrapper = counter.locator(
        "xpath=ancestor::*[.//text()[contains(., 'Next')]][1]"
    ).first

    # The post links live in a sibling container of the pagination wrapper.
    # Climb further up to the common ancestor that holds both.
    section = wrapper.locator(
        "xpath=ancestor::*[.//a[contains(@href,'/dxe-in-the-news/')]][1]"
    ).first

    for page_num in range(1, total_pages + 1):
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

        next_button = wrapper.get_by_text("Next", exact=True)
        if next_button.count() == 0:
            print("  no Next button found — stopping early")
            break

        next_button.first.click()
        try:
            page.wait_for_function(
                """(el, expected) => el.getAttribute('aria-label') === expected""",
                arg=[counter.element_handle(), f"Page {page_num + 1} of {total_pages}"],
                timeout=10000,
            )
        except Exception as e:
            print(f"  stopping: page didn't advance past {page_num} ({e})")
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

    # Sanity check: with ~9 posts per page, a near-complete scrape should
    # land well over 500 posts. If it's far short, something broke (e.g.
    # pagination stalled) — fail the job loudly instead of silently
    # "succeeding" with a small, misleading dataset.
    if len(posts) < 300:
        raise RuntimeError(
            f"Only scraped {len(posts)} posts — expected several hundred. "
            "Failing the job so this doesn't look like a clean success."
        )


if __name__ == "__main__":
    main()
