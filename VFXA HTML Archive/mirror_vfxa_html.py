#!/usr/bin/env python3

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.vfxapprentice.com"
LIBRARY_URL = f"{BASE_URL}/library"

# Your existing Google Drive archive.
DEFAULT_OUTPUT_DIR = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "vfx_apprentice_downloads"
)

# Existing Netscape-format browser cookie export.
DEFAULT_COOKIE_FILE = Path("cookies.txt")

# Optional SingleFile settings export.
DEFAULT_SETTINGS_FILE = Path("single-file-settings.json")

# Output reports are placed next to the script by default.
DEFAULT_REPORT_FILE = Path("vfxa_html_mirror_report.csv")

# Delay between discovery requests.
REQUEST_DELAY = 1.0

# Delay between SingleFile downloads.
DOWNLOAD_DELAY = 1.0

# Browser dimensions / rendering behavior.
BROWSER_WIDTH = "1920"
BROWSER_HEIGHT = "1080"
BROWSER_WAIT_UNTIL = "networkIdle"
BROWSER_WAIT_DELAY = "5000"

# Empty by default: mirror everything the authenticated library exposes.
#
# Examples:
# SKIP_PRODUCT_NAMES = {
#     "VFXA Free Training",
# }
#
# Do NOT put a product here unless you intentionally want to exclude it.
SKIP_PRODUCT_NAMES = set()


# ============================================================
# GENERAL HELPERS
# ============================================================

def sanitize_name(name: str) -> str:
    """
    Convert a web title into a safe macOS filename/folder name.
    """
    name = str(name).strip()

    # Characters problematic on common filesystems.
    name = re.sub(r'[\\/:*?"<>|]', "_", name)

    # Remove trailing dots/spaces.
    name = name.rstrip(". ")

    # Avoid completely empty names.
    return name or "_unnamed"


def normalize_url(url: str) -> str:
    """
    Normalize a URL so duplicate tracking fragments/queries do not
    create duplicate crawl entries.

    We intentionally preserve meaningful query parameters but remove
    fragments.
    """
    absolute = urljoin(BASE_URL, url)
    parsed = urlparse(absolute)

    # Only crawl the VFX Apprentice site.
    if parsed.netloc.lower() not in {
        "www.vfxapprentice.com",
        "vfxapprentice.com",
    }:
        return ""

    clean = parsed._replace(fragment="")
    return urlunparse(clean)


def is_vfxa_url(url: str) -> bool:
    parsed = urlparse(url)

    return parsed.netloc.lower() in {
        "www.vfxapprentice.com",
        "vfxapprentice.com",
    }


def parse_cookies(cookie_file: Path) -> dict:
    """
    Read a Netscape-format cookies.txt exported by a browser extension.
    """
    if not cookie_file.exists():
        raise FileNotFoundError(
            f"Cookie file not found:\n{cookie_file}\n\n"
            "Export your authenticated VFX Apprentice cookies as "
            "Netscape cookies.txt and place it at that path."
        )

    cookies = {}

    with cookie_file.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")

            # Netscape:
            # domain, flag, path, secure, expiration, name, value
            if len(parts) >= 7:
                name = parts[5]
                value = parts[6]

                if name:
                    cookies[name] = value

    if not cookies:
        raise RuntimeError(
            f"No usable cookies were found in:\n{cookie_file}\n\n"
            "Make sure the browser export is in Netscape cookies.txt format."
        )

    return cookies


def make_session(cookie_file: Path) -> requests.Session:
    cookies = parse_cookies(cookie_file)

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    session.cookies.update(cookies)

    return session


def fetch_html(
    session: requests.Session,
    url: str,
    timeout: int = 30,
) -> tuple[str | None, int | None]:

    time.sleep(REQUEST_DELAY)

    try:
        response = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
        )

        status = response.status_code

        if status != 200:
            print(f"  HTTP {status}: {url}")
            return None, status

        return response.text, status

    except requests.RequestException as exc:
        print(f"  REQUEST ERROR: {url}")
        print(f"    {exc}")
        return None, None


# ============================================================
# URL / NODE CLASSIFICATION
# ============================================================

def classify_url(url: str) -> str:
    """
    Identify the kind of VFX Apprentice page.

    Returns:
        library
        product
        category
        post
        other
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if path == "/library":
        return "library"

    if re.fullmatch(r"/products/[^/]+", path):
        return "product"

    if re.search(r"/products/[^/]+/categories/\d+$", path):
        return "category"

    if re.search(r"/products/[^/]+/categories/\d+/posts/\d+$", path):
        return "post"

    return "other"


# ============================================================
# PRODUCT / CATEGORY / POST EXTRACTION
# ============================================================

def extract_product_links(
    soup: BeautifulSoup,
) -> list[tuple[str, str]]:
    """
    Return (title, URL) pairs from the Library product cards.
    """
    results = []
    seen = set()

    for container in soup.find_all("div", class_="product"):
        title_element = container.find(
            "h4",
            class_="product__title",
        )

        link_element = container.find("a", href=True)

        if not title_element or not link_element:
            continue

        title = title_element.get_text(" ", strip=True)
        url = normalize_url(link_element["href"])

        if not url:
            continue

        if classify_url(url) != "product":
            continue

        key = (title, url)

        if key not in seen:
            seen.add(key)
            results.append(key)

    return results


def extract_category_and_post_links(
    soup: BeautifulSoup,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:

    categories = []
    posts = []

    seen_categories = set()
    seen_posts = set()

    # --------------------------------------------------------
    # Categories
    # --------------------------------------------------------

    for item in soup.find_all(
        "div",
        class_="category-listing",
    ):
        link = item.find("a", href=True)
        title = item.find("h4", class_="title")

        if not link or not title:
            continue

        title_text = title.get_text(" ", strip=True)
        url = normalize_url(link["href"])

        if not url:
            continue

        if classify_url(url) != "category":
            continue

        key = (title_text, url)

        if key not in seen_categories:
            seen_categories.add(key)
            categories.append(key)

    # --------------------------------------------------------
    # Posts / Lessons
    # --------------------------------------------------------

    for item in soup.find_all(
        "div",
        class_="post-listing",
    ):
        link = item.find("a", href=True)
        title = item.find("h4", class_="title")

        if not link or not title:
            continue

        title_text = title.get_text(" ", strip=True)
        url = normalize_url(link["href"])

        if not url:
            continue

        if classify_url(url) != "post":
            continue

        key = (title_text, url)

        if key not in seen_posts:
            seen_posts.add(key)
            posts.append(key)

    return categories, posts


# ============================================================
# LOCAL PATH CONSTRUCTION
# ============================================================

def local_path_for_node(
    node_type: str,
    product_name: str | None,
    path_parts: list[str],
    title: str,
    output_dir: Path,
) -> Path:

    # --------------------------------------------------------
    # Root library
    # --------------------------------------------------------

    if node_type == "library":
        return output_dir / "index.html"

    # --------------------------------------------------------
    # Product
    # --------------------------------------------------------

    if node_type == "product":
        product_folder = sanitize_name(title)

        return (
            output_dir
            / product_folder
            / "index.html"
        )

    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    if node_type == "category":
        product_folder = sanitize_name(product_name or "_unknown_product")

        folders = [
            sanitize_name(part)
            for part in path_parts
            if part.strip()
        ]

        # The category itself is the final directory.
        folders.append(sanitize_name(title))

        return (
            output_dir
            / product_folder
            / Path(*folders)
            / "index.html"
        )

    # --------------------------------------------------------
    # Lesson / post
    # --------------------------------------------------------

    if node_type == "post":
        product_folder = sanitize_name(product_name or "_unknown_product")

        folders = [
            sanitize_name(part)
            for part in path_parts
            if part.strip()
        ]

        directory = (
            output_dir
            / product_folder
            / Path(*folders)
        )

        filename = sanitize_name(title) + ".html"

        return directory / filename

    raise ValueError(f"Unknown node type: {node_type}")


# ============================================================
# DISCOVERY
# ============================================================

class VFXANode:
    def __init__(
        self,
        url: str,
        node_type: str,
        title: str,
        product_name: str | None,
        path_parts: list[str],
        parent_url: str | None = None,
    ):
        self.url = url
        self.node_type = node_type
        self.title = title
        self.product_name = product_name
        self.path_parts = list(path_parts)
        self.parent_url = parent_url


def discover_library(
    session: requests.Session,
) -> tuple[list[VFXANode], list[dict]]:

    discovered = []
    report = []

    queue = deque()

    # --------------------------------------------------------
    # Root
    # --------------------------------------------------------

    queue.append(
        VFXANode(
            url=LIBRARY_URL,
            node_type="library",
            title="Main Library",
            product_name=None,
            path_parts=[],
            parent_url=None,
        )
    )

    queued_urls = {LIBRARY_URL}
    processed_urls = set()

    print("=" * 75)
    print("PHASE 1 — DISCOVERING VFX APPRENTICE LIBRARY TREE")
    print("=" * 75)

    while queue:
        node = queue.popleft()

        if node.url in processed_urls:
            continue

        processed_urls.add(node.url)

        print()
        print(
            f"[{len(processed_urls)}] "
            f"{node.node_type.upper()}: {node.title}"
        )
        print(f"    {node.url}")

        html, status = fetch_html(session, node.url)

        if html is None:
            report.append({
                "type": node.node_type,
                "title": node.title,
                "url": node.url,
                "local_path": "",
                "status": f"DISCOVERY_FAILED_{status or 'REQUEST_ERROR'}",
            })
            continue

        discovered.append(node)

        local_path = ""

        report.append({
            "type": node.node_type,
            "title": node.title,
            "url": node.url,
            "local_path": local_path,
            "status": "DISCOVERED",
        })

        soup = BeautifulSoup(html, "html.parser")

        # ----------------------------------------------------
        # Library -> Products
        # ----------------------------------------------------

        if node.node_type == "library":

            products = extract_product_links(soup)

            print(
                f"    Products discovered on Library: {len(products)}"
            )

            for title, url in products:

                if title in SKIP_PRODUCT_NAMES:
                    print(f"    Skipping product: {title}")
                    continue

                if url in queued_urls:
                    continue

                queued_urls.add(url)

                queue.append(
                    VFXANode(
                        url=url,
                        node_type="product",
                        title=title,
                        product_name=title,
                        path_parts=[],
                        parent_url=node.url,
                    )
                )

        # ----------------------------------------------------
        # Product / Category -> Categories + Posts
        # ----------------------------------------------------

        elif node.node_type in {"product", "category"}:

            categories, posts = extract_category_and_post_links(soup)

            print(
                f"    Categories: {len(categories)} | "
                f"Lessons/posts: {len(posts)}"
            )

            # -----------------------------------------------
            # Child categories
            # -----------------------------------------------

            for title, url in categories:

                if url in queued_urls:
                    continue

                queued_urls.add(url)

                if node.node_type == "product":
                    child_path_parts = []
                else:
                    child_path_parts = list(node.path_parts)

                queue.append(
                    VFXANode(
                        url=url,
                        node_type="category",
                        title=title,
                        product_name=node.product_name,
                        path_parts=child_path_parts,
                        parent_url=node.url,
                    )
                )

            # -----------------------------------------------
            # Child lessons
            # -----------------------------------------------

            for title, url in posts:

                if url in queued_urls:
                    continue

                queued_urls.add(url)

                # A lesson directly underneath a product has no
                # category component in its local path.
                if node.node_type == "product":
                    lesson_path_parts = []
                else:
                    lesson_path_parts = list(node.path_parts)

                queue.append(
                    VFXANode(
                        url=url,
                        node_type="post",
                        title=title,
                        product_name=node.product_name,
                        path_parts=lesson_path_parts,
                        parent_url=node.url,
                    )
                )

        # ----------------------------------------------------
        # Lesson pages are leaf nodes.
        # ----------------------------------------------------

        elif node.node_type == "post":
            pass

    print()
    print("=" * 75)
    print("DISCOVERY COMPLETE")
    print("=" * 75)

    counts = {
        "library": 0,
        "product": 0,
        "category": 0,
        "post": 0,
    }

    for node in discovered:
        counts[node.node_type] += 1

    print(f"Library pages   : {counts['library']}")
    print(f"Product pages   : {counts['product']}")
    print(f"Category pages  : {counts['category']}")
    print(f"Lesson pages    : {counts['post']}")
    print(f"TOTAL HTML PAGES: {len(discovered)}")

    return discovered, report


# ============================================================
# SINGLEFILE
# ============================================================

def verify_single_file() -> None:
    """
    Verify the SingleFile CLI is available.
    """
    result = subprocess.run(
        ["single-file", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print(
            "ERROR: Could not execute 'single-file'.\n\n"
            "Install/configure SingleFile CLI first."
        )

        if result.stderr.strip():
            print(result.stderr.strip())

        sys.exit(1)

    version = result.stdout.strip()

    print(f"SingleFile: {version}")


def download_with_single_file(
    node: VFXANode,
    output_dir: Path,
    cookie_file: Path,
    settings_file: Path | None,
) -> tuple[bool, str]:

    target_path = local_path_for_node(
        node_type=node.node_type,
        product_name=node.product_name,
        path_parts=node.path_parts,
        title=node.title,
        output_dir=output_dir,
    )

    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Existing non-empty file = already complete enough for this pass.
    if target_path.exists() and target_path.stat().st_size > 0:
        return True, "ALREADY_EXISTS"

    command = [
        "single-file",
        "--browser-cookies-file",
        str(cookie_file),
        "--output-directory",
        str(target_path.parent),
        "--browser-width",
        BROWSER_WIDTH,
        "--browser-height",
        BROWSER_HEIGHT,
        "--browser-wait-until",
        BROWSER_WAIT_UNTIL,
        "--browser-wait-delay",
        BROWSER_WAIT_DELAY,
    ]

    if settings_file is not None and settings_file.exists():
        command.extend([
            "--settings-file",
            str(settings_file),
        ])

    command.extend([
        node.url,
        target_path.name,
    ])

    time.sleep(DOWNLOAD_DELAY)

    print()
    print(f"DOWNLOAD: {node.node_type.upper()}")
    print(f"  Title : {node.title}")
    print(f"  URL   : {node.url}")
    print(f"  Save  : {target_path}")

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print("  FAILED")

        if result.stdout.strip():
            print(result.stdout.strip())

        if result.stderr.strip():
            print(result.stderr.strip())

        return False, "SINGLEFILE_FAILED"

    if not target_path.exists():
        print("  FAILED: SingleFile returned success but file is missing.")
        return False, "OUTPUT_MISSING"

    size = target_path.stat().st_size

    if size == 0:
        print("  FAILED: output file is empty.")
        return False, "OUTPUT_EMPTY"

    print(
        f"  OK ({size / 1024 / 1024:.2f} MB)"
    )

    return True, "DOWNLOADED"


# ============================================================
# REPORTING
# ============================================================

def write_report(
    report_file: Path,
    rows: list[dict],
) -> None:

    report_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "type",
        "title",
        "url",
        "local_path",
        "status",
        "size_bytes",
    ]

    with report_file.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in rows:
            normalized = {
                "type": row.get("type", ""),
                "title": row.get("title", ""),
                "url": row.get("url", ""),
                "local_path": row.get("local_path", ""),
                "status": row.get("status", ""),
                "size_bytes": row.get("size_bytes", ""),
            }

            writer.writerow(normalized)


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Mirror the authenticated VFX Apprentice Library "
            "HTML hierarchy into an offline folder."
        )
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Root VFX Apprentice archive directory.",
    )

    parser.add_argument(
        "--cookies",
        type=Path,
        default=DEFAULT_COOKIE_FILE,
        help="Netscape browser cookies.txt.",
    )

    parser.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_SETTINGS_FILE,
        help="Optional SingleFile settings JSON.",
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_FILE,
        help="CSV report path.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Download only the first N discovered pages. "
            "0 means all."
        ),
    )

    parser.add_argument(
        "--discover-only",
        action="store_true",
        help=(
            "Discover and report the library tree, "
            "but do not download HTML."
        ),
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    cookie_file = args.cookies.expanduser().resolve()
    settings_file = args.settings.expanduser().resolve()
    report_file = args.report.expanduser().resolve()

    print("=" * 75)
    print("VFX APPRENTICE OFFLINE HTML MIRROR")
    print("=" * 75)

    print()
    print(f"Output directory : {output_dir}")
    print(f"Cookie file      : {cookie_file}")
    print(f"Settings file    : {settings_file}")
    print(f"Report file      : {report_file}")

    # --------------------------------------------------------
    # Safety checks
    # --------------------------------------------------------

    if not output_dir.exists():
        print()
        print("Creating output directory...")
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    if not cookie_file.exists():
        raise FileNotFoundError(
            f"\nCookie file does not exist:\n{cookie_file}"
        )

    verify_single_file()

    session = make_session(cookie_file)

    # --------------------------------------------------------
    # Discover hierarchy
    # --------------------------------------------------------

    discovered, initial_report = discover_library(session)

    if not discovered:
        raise RuntimeError(
            "\nNo pages were discovered.\n"
            "This usually means the authentication cookies are invalid "
            "or expired."
        )

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    if args.discover_only:

        print()
        print(
            "DISCOVER-ONLY mode enabled. "
            "No HTML files will be downloaded."
        )

        report_rows = []

        for row in initial_report:
            report_rows.append({
                **row,
                "local_path": "",
                "size_bytes": "",
            })

        write_report(
            report_file,
            report_rows,
        )

        print()
        print(f"Discovery report written to:\n{report_file}")
        return

    print()
    print("=" * 75)
    print("PHASE 2 — DOWNLOADING HTML PAGES")
    print("=" * 75)

    nodes_to_download = list(discovered)

    if args.limit > 0:
        nodes_to_download = nodes_to_download[:args.limit]

        print()
        print(
            f"LIMIT MODE: only the first "
            f"{len(nodes_to_download)} pages will be processed."
        )

    report_rows = []

    success_count = 0
    existing_count = 0
    failure_count = 0

    for index, node in enumerate(nodes_to_download, start=1):

        target_path = local_path_for_node(
            node_type=node.node_type,
            product_name=node.product_name,
            path_parts=node.path_parts,
            title=node.title,
            output_dir=output_dir,
        )

        success, status = download_with_single_file(
            node=node,
            output_dir=output_dir,
            cookie_file=cookie_file,
            settings_file=(
                settings_file
                if settings_file.exists()
                else None
            ),
        )

        size_bytes = ""

        if target_path.exists():
            try:
                size_bytes = target_path.stat().st_size
            except OSError:
                size_bytes = ""

        if success:
            success_count += 1

            if status == "ALREADY_EXISTS":
                existing_count += 1

        else:
            failure_count += 1

        report_rows.append({
            "type": node.node_type,
            "title": node.title,
            "url": node.url,
            "local_path": str(
                target_path.relative_to(output_dir)
            ),
            "status": status,
            "size_bytes": size_bytes,
        })

        print(
            f"\nProgress: {index}/{len(nodes_to_download)}"
        )

    # --------------------------------------------------------
    # Save report
    # --------------------------------------------------------

    write_report(
        report_file,
        report_rows,
    )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print()
    print("=" * 75)
    print("HTML MIRROR COMPLETE")
    print("=" * 75)

    print()
    print(f"Pages discovered         : {len(discovered)}")
    print(f"Pages processed          : {len(nodes_to_download)}")
    print(f"Successful               : {success_count}")
    print(f"Already existed          : {existing_count}")
    print(f"Failed                   : {failure_count}")

    print()
    print(f"Archive root:")
    print(f"  {output_dir}")

    print()
    print(f"Report:")
    print(f"  {report_file}")

    if failure_count:
        print()
        print(
            "WARNING: Some pages failed. "
            "The CSV report contains the exact URLs and statuses."
        )
    else:
        print()
        print("All processed HTML pages were successfully saved.")

    print()
    print("Existing MP4 and resource files were not modified.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nStopped by user.")
        sys.exit(130)
    except Exception as exc:
        print()
        print("=" * 75)
        print("FATAL ERROR")
        print("=" * 75)
        print(str(exc))
        sys.exit(1)