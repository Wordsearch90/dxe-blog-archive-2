# DxE Blog Archive

Full-text search over every blog post at directactioneverywhere.com/news.

## How it works
- `scrape.py` uses a real headless browser (Playwright) to click through
  every page of the Blog tab (its pagination is JavaScript-driven, so a
  plain HTTP fetch can't do this — a browser is required), collect every
  post URL, then visit each post to save its title, date, and full text
  to `docs/posts.json`.
- `docs/index.html` is a static search page that loads `posts.json` and
  filters posts client-side as you type. GitHub Pages serves this folder.
- `.github/workflows/scrape.yml` runs the scraper on GitHub's servers
  (manually, or automatically every Monday) and commits the updated data.

## One-time setup
1. Add all these files to your repo (see chat for exact steps).
2. In the repo: **Settings → Pages** → under "Build and deployment",
   set Source = `Deploy from a branch`, Branch = `main`, folder = `/docs`.
   Save. GitHub will give you a URL like
   `https://wordsearch90.github.io/dxe-blog-archive/`.
3. In the repo: **Actions** tab → you should see "Scrape DxE Blog" listed.
   Click it, then click **Run workflow** → **Run workflow**. It takes a
   few minutes (visiting ~690 pages one by one).
4. Once it finishes (green checkmark), refresh your Pages URL — the
   archive will be searchable.

## Updating later
The workflow re-runs automatically every Monday, or run it manually
anytime from the Actions tab.
