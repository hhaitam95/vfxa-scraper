#!/usr/bin/env python3

"""
VFX Apprentice — Full HTML Library Mirror

PURPOSE
-------
Mirror the complete authenticated VFX Apprentice library hierarchy
into the local Google Drive archive.

This version is intentionally HTML-only.

It does NOT download or modify:
    MP4
    ZIP
    RAR
    7Z
    PDF
    images
    or any other resource files.

HTML behavior:
    Existing HTML -> REPLACE
    Missing HTML  -> DOWNLOAD

LIBRARY SCOPE
-------------
Included:
    VFX Apprentice Asset Library
    Hand-Drawn 2D FX: Level 1
    Hand-Drawn 2D FX: Level 2
    Hand-Crafted 3D VFX: Level 1
    Hand-Crafted 3D VFX: Level 2
    Apprenticeship Level 3

Skipped:
    Beginner Bootcamp
    VFXA Free Training

HIERARCHY
---------
/library
    -> product
        -> category
            -> nested category
                -> lesson/post

LOCAL STRUCTURE
---------------
VFX Apprentice Downloads/
    index.html

    Product/
        index.html

        Category/
            index.html

            Nested Category/
                index.html

                Lesson.html

IMPORTANT
---------
The SingleFile CLI receives the COMPLETE ABSOLUTE destination
path as its output argument. This was validated successfully
with the 4-page path test.

Requirements:
    Python 3
    requests
    beautifulsoup4
    SingleFile CLI
    authenticated Netscape cookies.txt
"""


import csv
import json
import re
import subprocess
import sys
import time

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

from collections import deque
from pathlib import Path
from typing import Optional
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.vfxapprentice.com"
LIBRARY_URL = f"{BASE_URL}/library"

# ------------------------------------------------------------
# CORRECT ARCHIVE ROOT
# ------------------------------------------------------------

OUTPUT_DIR = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

# ------------------------------------------------------------
# AUTHENTICATION
# ------------------------------------------------------------

COOKIE_FILE = Path("cookies.txt")

# ------------------------------------------------------------
# REPORTS
# ------------------------------------------------------------

DISCOVERY_REPORT = Path(
    "vfxa_library_tree.csv"
)

HTML_REPORT = Path(
    "vfxa_html_download_report.csv"
)

STATE_FILE = Path(
    "vfxa_mirror_state.json"
)

# ------------------------------------------------------------
# PRODUCTS TO SKIP
# ------------------------------------------------------------

SKIP_PRODUCTS = {
    "Beginner Bootcamp",
    "VFXA Free Training",
}

# ------------------------------------------------------------
# PERFORMANCE
# ------------------------------------------------------------

# Number of simultaneous SingleFile/Chromium processes.
#
# 4 is the validated setting from the previous run.
SINGLEFILE_WORKERS = 4

# Number of simultaneous HTTP discovery requests.
REQUEST_WORKERS = 6

# Delay before normal HTTP requests.
REQUEST_DELAY = 0.5

# Delay before SingleFile jobs.
DOWNLOAD_DELAY = 0.25

# ------------------------------------------------------------
# SINGLEFILE BROWSER
# ------------------------------------------------------------

BROWSER_WIDTH = "1920"
BROWSER_HEIGHT = "1080"

BROWSER_WAIT_UNTIL = "networkIdle"

# 1 second rather than the old 5 second delay.
BROWSER_WAIT_DELAY = "1000"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# ============================================================
# GENERAL HELPERS
# ============================================================

def sanitize_name(
    name: str,
) -> str:
    """
    Convert a VFX Apprentice title into a safe macOS
    filename/folder name.
    """

    name = str(name).strip()

    name = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        name,
    )

    name = name.rstrip(
        " ."
    )

    return name or "_unnamed"


def normalize_vfxa_url(
    url: str,
) -> str:
    """
    Convert relative URLs into absolute VFXA URLs
    and remove fragments.
    """

    if not url:
        return ""

    absolute = urljoin(
        BASE_URL,
        url,
    )

    parsed = urlparse(
        absolute
    )

    if parsed.netloc.lower() not in {
        "www.vfxapprentice.com",
        "vfxapprentice.com",
    }:
        return ""

    parsed = parsed._replace(
        fragment=""
    )

    return urlunparse(
        parsed
    )


def classify_url(
    url: str,
) -> str:
    """
    Classify a VFX Apprentice page.
    """

    path = urlparse(
        url
    ).path.rstrip("/")

    if path == "/library":
        return "library"

    if re.fullmatch(
        r"/products/[^/]+",
        path,
    ):
        return "product"

    if re.fullmatch(
        r"/products/[^/]+/categories/\d+",
        path,
    ):
        return "category"

    if re.fullmatch(
        r"/products/[^/]+/categories/\d+/posts/\d+",
        path,
    ):
        return "post"

    return "other"


def archive_relative(
    path: Path,
) -> str:
    """
    Convert an absolute path to a path relative to the archive.
    """

    try:
        return str(
            path.relative_to(
                OUTPUT_DIR
            )
        )

    except ValueError:

        return str(path)


# ============================================================
# COOKIES
# ============================================================

def parse_cookies(
    cookie_file: Path,
) -> dict:

    if not cookie_file.exists():

        raise FileNotFoundError(
            f"Cookie file not found:\n"
            f"{cookie_file}"
        )

    cookies = {}

    with cookie_file.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:

        for line in f:

            line = line.strip()

            if (
                not line
                or line.startswith("#")
            ):
                continue

            parts = line.split(
                "\t"
            )

            if len(parts) >= 7:

                name = parts[5].strip()
                value = parts[6].strip()

                if name:
                    cookies[name] = value

    if not cookies:

        raise RuntimeError(
            "No usable cookies found in "
            f"{cookie_file}"
        )

    return cookies


def create_session() -> requests.Session:

    session = requests.Session()

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": (
            "en-US,en;q=0.9"
        ),
    })

    session.cookies.update(
        parse_cookies(
            COOKIE_FILE
        )
    )

    return session


# ============================================================
# HTTP FETCH
# ============================================================

def fetch_page(
    session: requests.Session,
    url: str,
) -> tuple[
    Optional[str],
    Optional[int],
]:

    if REQUEST_DELAY > 0:
        time.sleep(
            REQUEST_DELAY
        )

    try:

        response = session.get(
            url,
            timeout=30,
            allow_redirects=True,
        )

        if response.status_code != 200:

            return (
                None,
                response.status_code,
            )

        return (
            response.text,
            response.status_code,
        )

    except requests.RequestException:

        return (
            None,
            None,
        )


# ============================================================
# NODE
# ============================================================

class Node:

    def __init__(
        self,
        url: str,
        node_type: str,
        title: str,
        product_name: Optional[str],
        path_parts: list[str],
        parent_url: Optional[str],
    ):

        self.url = url
        self.node_type = node_type
        self.title = title
        self.product_name = product_name
        self.path_parts = list(
            path_parts
        )
        self.parent_url = parent_url

    def local_path(self) -> Path:

        # ----------------------------------------------------
        # Root library
        # ----------------------------------------------------

        if self.node_type == "library":

            return (
                OUTPUT_DIR
                / "index.html"
            )

        # ----------------------------------------------------
        # Product
        # ----------------------------------------------------

        if self.node_type == "product":

            return (
                OUTPUT_DIR
                / sanitize_name(
                    self.title
                )
                / "index.html"
            )

        # ----------------------------------------------------
        # Product + hierarchy
        # ----------------------------------------------------

        product_folder = sanitize_name(
            self.product_name
            or "_unknown_product"
        )

        folders = [
            sanitize_name(part)
            for part in self.path_parts
            if str(part).strip()
        ]

        # ----------------------------------------------------
        # Category
        # ----------------------------------------------------

        if self.node_type == "category":

            folders.append(
                sanitize_name(
                    self.title
                )
            )

            return (
                OUTPUT_DIR
                / product_folder
                / Path(*folders)
                / "index.html"
            )

        # ----------------------------------------------------
        # Lesson/Post
        # ----------------------------------------------------

        if self.node_type == "post":

            filename = (
                sanitize_name(
                    self.title
                )
                + ".html"
            )

            return (
                OUTPUT_DIR
                / product_folder
                / Path(*folders)
                / filename
            )

        raise ValueError(
            f"Unsupported node type: "
            f"{self.node_type}"
        )


# ============================================================
# PAGE STRUCTURE PARSING
# ============================================================

def extract_products(
    soup: BeautifulSoup,
) -> list[tuple[str, str]]:

    results = []
    seen = set()

    for container in soup.find_all(
        "div",
        class_="product",
    ):

        title_element = container.find(
            "h4",
            class_="product__title",
        )

        link_element = container.find(
            "a",
            href=True,
        )

        if (
            not title_element
            or not link_element
        ):
            continue

        title = title_element.get_text(
            " ",
            strip=True,
        )

        url = normalize_vfxa_url(
            link_element["href"]
        )

        if not url:
            continue

        if classify_url(url) != "product":
            continue

        if title in SKIP_PRODUCTS:
            continue

        item = (
            title,
            url,
        )

        if item not in seen:

            seen.add(
                item
            )

            results.append(
                item
            )

    return results


def extract_categories_and_posts(
    soup: BeautifulSoup,
) -> tuple[
    list[tuple[str, str]],
    list[tuple[str, str]],
]:

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

        link = item.find(
            "a",
            href=True,
        )

        title = item.find(
            "h4",
            class_="title",
        )

        if (
            not link
            or not title
        ):
            continue

        title_text = title.get_text(
            " ",
            strip=True,
        )

        url = normalize_vfxa_url(
            link["href"]
        )

        if not url:
            continue

        if classify_url(url) != "category":
            continue

        pair = (
            title_text,
            url,
        )

        if pair not in seen_categories:

            seen_categories.add(
                pair
            )

            categories.append(
                pair
            )

    # --------------------------------------------------------
    # Posts / lessons
    # --------------------------------------------------------

    for item in soup.find_all(
        "div",
        class_="post-listing",
    ):

        link = item.find(
            "a",
            href=True,
        )

        title = item.find(
            "h4",
            class_="title",
        )

        if (
            not link
            or not title
        ):
            continue

        title_text = title.get_text(
            " ",
            strip=True,
        )

        url = normalize_vfxa_url(
            link["href"]
        )

        if not url:
            continue

        if classify_url(url) != "post":
            continue

        pair = (
            title_text,
            url,
        )

        if pair not in seen_posts:

            seen_posts.add(
                pair
            )

            posts.append(
                pair
            )

    return (
        categories,
        posts,
    )


# ============================================================
# FULL TREE DISCOVERY
# ============================================================

def discover_tree(
    session: requests.Session,
) -> tuple[
    list[Node],
    dict[str, str],
]:

    print()
    print("=" * 78)
    print(
        "PHASE 1 — DISCOVERING COMPLETE LIBRARY TREE"
    )
    print("=" * 78)

    root = Node(
        url=LIBRARY_URL,
        node_type="library",
        title="Main Library",
        product_name=None,
        path_parts=[],
        parent_url=None,
    )

    queue = deque([
        root
    ])

    queued_urls = {
        LIBRARY_URL
    }

    visited = set()

    nodes = []

    errors = {}

    while queue:

        node = queue.popleft()

        if node.url in visited:
            continue

        visited.add(
            node.url
        )

        display_number = (
            len(nodes)
            + len(errors)
            + 1
        )

        print(
            f"[{display_number}] "
            f"{node.node_type.upper():8} "
            f"{node.title}"
        )

        html, status = fetch_page(
            session,
            node.url,
        )

        if html is None:

            errors[node.url] = (
                f"HTTP_{status}"
                if status
                else "REQUEST_ERROR"
            )

            continue

        nodes.append(
            node
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        # ----------------------------------------------------
        # Library -> Product
        # ----------------------------------------------------

        if node.node_type == "library":

            products = extract_products(
                soup
            )

            for title, url in products:

                if url in queued_urls:
                    continue

                queued_urls.add(
                    url
                )

                queue.append(
                    Node(
                        url=url,
                        node_type="product",
                        title=title,
                        product_name=title,
                        path_parts=[],
                        parent_url=node.url,
                    )
                )

        # ----------------------------------------------------
        # Product/category -> category/post
        # ----------------------------------------------------

        elif node.node_type in {
            "product",
            "category",
        }:

            categories, posts = (
                extract_categories_and_posts(
                    soup
                )
            )

            # ------------------------------------------------
            # Categories
            # ------------------------------------------------

            for title, url in categories:

                if url in queued_urls:
                    continue

                queued_urls.add(
                    url
                )

                # Product -> Category
                if node.node_type == "product":

                    child_path = []

                # Category -> Nested Category
                else:

                    child_path = (
                        list(
                            node.path_parts
                        )
                        + [node.title]
                    )

                queue.append(
                    Node(
                        url=url,
                        node_type="category",
                        title=title,
                        product_name=node.product_name,
                        path_parts=child_path,
                        parent_url=node.url,
                    )
                )

            # ------------------------------------------------
            # Lessons
            # ------------------------------------------------

            for title, url in posts:

                if url in queued_urls:
                    continue

                queued_urls.add(
                    url
                )

                # Product -> Lesson
                if node.node_type == "product":

                    lesson_path = []

                # Category -> Lesson
                else:

                    lesson_path = (
                        list(
                            node.path_parts
                        )
                        + [node.title]
                    )

                queue.append(
                    Node(
                        url=url,
                        node_type="post",
                        title=title,
                        product_name=node.product_name,
                        path_parts=lesson_path,
                        parent_url=node.url,
                    )
                )

    print()
    print("=" * 78)
    print(
        "DISCOVERY COMPLETE"
    )
    print("=" * 78)

    type_counts = {
        "library": 0,
        "product": 0,
        "category": 0,
        "post": 0,
    }

    for node in nodes:

        type_counts[
            node.node_type
        ] += 1

    print(
        f"Library   : "
        f"{type_counts['library']}"
    )

    print(
        f"Products  : "
        f"{type_counts['product']}"
    )

    print(
        f"Categories: "
        f"{type_counts['category']}"
    )

    print(
        f"Lessons   : "
        f"{type_counts['post']}"
    )

    print(
        f"TOTAL     : "
        f"{len(nodes)}"
    )

    print(
        f"Errors    : "
        f"{len(errors)}"
    )

    return (
        nodes,
        errors,
    )


# ============================================================
# DISCOVERY REPORT
# ============================================================

def write_discovery_report(
    nodes: list[Node],
    errors: dict[str, str],
) -> None:

    with DISCOVERY_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        fields = [
            "type",
            "title",
            "url",
            "parent_url",
            "local_path",
            "status",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for node in nodes:

            writer.writerow({
                "type":
                    node.node_type,
                "title":
                    node.title,
                "url":
                    node.url,
                "parent_url":
                    node.parent_url or "",
                "local_path":
                    archive_relative(
                        node.local_path()
                    ),
                "status":
                    "DISCOVERED",
            })

        for url, error in errors.items():

            writer.writerow({
                "type":
                    classify_url(url),
                "title":
                    "",
                "url":
                    url,
                "parent_url":
                    "",
                "local_path":
                    "",
                "status":
                    error,
            })


# ============================================================
# SINGLEFILE VERSION
# ============================================================

def verify_singlefile() -> None:

    try:

        result = subprocess.run(
            [
                "single-file",
                "--version",
            ],
            capture_output=True,
            text=True,
        )

    except OSError as exc:

        raise RuntimeError(
            "Could not execute SingleFile."
        ) from exc

    if result.returncode != 0:

        raise RuntimeError(
            "SingleFile is not working:\n"
            + (
                result.stderr.strip()
                or result.stdout.strip()
            )
        )

    print(
        f"SingleFile: "
        f"{result.stdout.strip()}"
    )


# ============================================================
# SINGLEFILE CAPTURE
# ============================================================

def capture_one_page(
    node: Node,
) -> dict:

    target = node.local_path()

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    existed_before = (
        target.exists()
        and target.stat().st_size > 0
    )

    if DOWNLOAD_DELAY > 0:

        time.sleep(
            DOWNLOAD_DELAY
        )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # We pass the COMPLETE ABSOLUTE destination path as the
    # output argument.
    #
    # This was validated by the 4-page path test.
    # --------------------------------------------------------

    command = [
        "single-file",

        "--browser-cookies-file",
        str(COOKIE_FILE),

        "--browser-width",
        BROWSER_WIDTH,

        "--browser-height",
        BROWSER_HEIGHT,

        "--browser-wait-until",
        BROWSER_WAIT_UNTIL,

        "--browser-wait-delay",
        BROWSER_WAIT_DELAY,

        # Existing HTML should be overwritten.
        "--filename-conflict-action",
        "overwrite",

        node.url,

        # COMPLETE destination path.
        str(target),
    ]

    started = time.monotonic()

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

    except Exception as exc:

        return {
            "node": node,
            "status": "FAILED_PROCESS",
            "size": 0,
            "seconds":
                time.monotonic()
                - started,
            "error": str(exc),
        }

    elapsed = (
        time.monotonic()
        - started
    )

    if result.returncode != 0:

        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown SingleFile error"
        )

        return {
            "node": node,
            "status":
                "FAILED_SINGLEFILE",
            "size": 0,
            "seconds": elapsed,
            "error": error_text,
        }

    if not target.exists():

        return {
            "node": node,
            "status":
                "FAILED_OUTPUT_MISSING",
            "size": 0,
            "seconds": elapsed,
            "error": "",
        }

    size = target.stat().st_size

    if size == 0:

        return {
            "node": node,
            "status":
                "FAILED_OUTPUT_EMPTY",
            "size": 0,
            "seconds": elapsed,
            "error": "",
        }

    return {
        "node": node,
        "status": (
            "REPLACED"
            if existed_before
            else "DOWNLOADED"
        ),
        "size": size,
        "seconds": elapsed,
        "error": "",
    }


# ============================================================
# HTML CAPTURE BATCH
# ============================================================

def capture_all_html(
    nodes: list[Node],
) -> list[dict]:

    print()
    print("=" * 78)
    print(
        "PHASE 2 — CAPTURING HTML"
    )
    print("=" * 78)

    total = len(nodes)

    print()
    print(
        f"Pages to capture: {total}"
    )

    print(
        f"SingleFile workers: "
        f"{SINGLEFILE_WORKERS}"
    )

    print(
        f"SingleFile wait: "
        f"{BROWSER_WAIT_UNTIL} "
        f"+ {BROWSER_WAIT_DELAY} ms"
    )

    print()

    results = []

    started = time.monotonic()

    completed = 0
    failures = 0

    with ThreadPoolExecutor(
        max_workers=SINGLEFILE_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                capture_one_page,
                node,
            ): node
            for node in nodes
        }

        for future in as_completed(
            futures
        ):

            node = futures[
                future
            ]

            try:

                result = future.result()

            except Exception as exc:

                result = {
                    "node": node,
                    "status":
                        "FAILED_EXCEPTION",
                    "size": 0,
                    "seconds": 0,
                    "error": str(exc),
                }

            results.append(
                result
            )

            completed += 1

            if result[
                "status"
            ].startswith("FAILED"):

                failures += 1

            elapsed = (
                time.monotonic()
                - started
            )

            rate = (
                completed / elapsed
                if elapsed > 0
                else 0
            )

            remaining = (
                total
                - completed
            )

            eta_seconds = (
                remaining / rate
                if rate > 0
                else 0
            )

            eta_minutes = (
                eta_seconds / 60
            )

            if result[
                "status"
            ].startswith("FAILED"):

                marker = "FAILED"

            elif result[
                "status"
            ] == "REPLACED":

                marker = "REPLACED"

            else:

                marker = "OK"

            print(
                f"[{completed:4d}/{total}] "
                f"{marker:9} "
                f"{node.node_type:8} "
                f"{node.title[:55]}"
            )

            if completed >= 5:

                print(
                    f"          "
                    f"Rate: "
                    f"{rate:.3f} pages/sec | "
                    f"ETA: "
                    f"{eta_minutes:.1f} min"
                )

            if (
                result.get("error")
                and result[
                    "status"
                ].startswith("FAILED")
            ):

                print(
                    f"          "
                    f"{result['error'][:300]}"
                )

    elapsed_total = (
        time.monotonic()
        - started
    )

    print()
    print(
        "=" * 78
    )

    print(
        "HTML CAPTURE COMPLETE"
    )

    print(
        "=" * 78
    )

    print(
        f"Pages processed: "
        f"{completed}"
    )

    print(
        f"Failures: "
        f"{failures}"
    )

    print(
        f"Elapsed: "
        f"{elapsed_total / 60:.1f} minutes"
    )

    if elapsed_total > 0:

        print(
            f"Average: "
            f"{completed / elapsed_total:.3f} "
            f"pages/sec"
        )

    return results


# ============================================================
# HTML REPORT
# ============================================================

def write_html_report(
    results: list[dict],
) -> None:

    with HTML_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        fields = [
            "type",
            "title",
            "url",
            "parent_url",
            "local_path",
            "status",
            "size_bytes",
            "seconds",
            "error",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for result in results:

            node = result[
                "node"
            ]

            writer.writerow({
                "type":
                    node.node_type,
                "title":
                    node.title,
                "url":
                    node.url,
                "parent_url":
                    node.parent_url or "",
                "local_path":
                    archive_relative(
                        node.local_path()
                    ),
                "status":
                    result[
                        "status"
                    ],
                "size_bytes":
                    result.get(
                        "size",
                        0,
                    ),
                "seconds":
                    f"{result.get('seconds', 0):.3f}",
                "error":
                    result.get(
                        "error",
                        "",
                    ),
            })


# ============================================================
# STATE
# ============================================================

def save_state(
    nodes: list[Node],
    results: list[dict],
) -> None:

    state = {
        "timestamp": time.time(),
        "archive_root":
            str(OUTPUT_DIR),
        "total_nodes":
            len(nodes),
        "pages": {},
    }

    for result in results:

        node = result[
            "node"
        ]

        state[
            "pages"
        ][node.url] = {
            "type":
                node.node_type,
            "title":
                node.title,
            "local_path":
                archive_relative(
                    node.local_path()
                ),
            "status":
                result[
                    "status"
                ],
            "size_bytes":
                result.get(
                    "size",
                    0,
                ),
            "seconds":
                result.get(
                    "seconds",
                    0,
                ),
        }

    temporary = STATE_FILE.with_name(
        STATE_FILE.name
        + ".tmp"
    )

    with temporary.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False,
        )

    temporary.replace(
        STATE_FILE
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE FULL HTML LIBRARY MIRROR"
    )
    print("=" * 78)

    print()
    print(
        "Archive:"
    )
    print(
        f"  {OUTPUT_DIR}"
    )

    print()
    print(
        "Cookies:"
    )
    print(
        f"  {COOKIE_FILE}"
    )

    print()
    print(
        "Skipped products:"
    )

    for product in sorted(
        SKIP_PRODUCTS
    ):

        print(
            f"  - {product}"
        )

    print()
    print(
        "HTML policy:"
    )

    print(
        "  Existing HTML -> REPLACE"
    )

    print(
        "  Missing HTML  -> DOWNLOAD"
    )

    print()
    print(
        "MP4 / ZIP policy:"
    )

    print(
        "  NOT TOUCHED"
    )

    # --------------------------------------------------------
    # Setup
    # --------------------------------------------------------

    if not COOKIE_FILE.exists():

        raise FileNotFoundError(
            f"Missing cookie file:\n"
            f"{COOKIE_FILE}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    verify_singlefile()

    session = create_session()

    # --------------------------------------------------------
    # Discover
    # --------------------------------------------------------

    nodes, errors = discover_tree(
        session
    )

    if not nodes:

        raise RuntimeError(
            "No pages were discovered."
        )

    write_discovery_report(
        nodes,
        errors,
    )

    # --------------------------------------------------------
    # Capture
    # --------------------------------------------------------

    results = capture_all_html(
        nodes
    )

    # --------------------------------------------------------
    # Reports / state
    # --------------------------------------------------------

    write_html_report(
        results
    )

    save_state(
        nodes,
        results
    )

    # --------------------------------------------------------
    # Final statistics
    # --------------------------------------------------------

    successful = sum(
        1
        for result in results
        if not result[
            "status"
        ].startswith("FAILED")
    )

    failures = sum(
        1
        for result in results
        if result[
            "status"
        ].startswith("FAILED")
    )

    replaced = sum(
        1
        for result in results
        if result[
            "status"
        ] == "REPLACED"
    )

    downloaded = sum(
        1
        for result in results
        if result[
            "status"
        ] == "DOWNLOADED"
    )

    print()
    print("=" * 78)
    print(
        "FINAL SUMMARY"
    )
    print("=" * 78)

    print()
    print(
        "DISCOVERY"
    )

    print(
        f"  Pages discovered : "
        f"{len(nodes)}"
    )

    print(
        f"  Discovery errors : "
        f"{len(errors)}"
    )

    print()
    print(
        "HTML"
    )

    print(
        f"  Downloaded       : "
        f"{downloaded}"
    )

    print(
        f"  Replaced         : "
        f"{replaced}"
    )

    print(
        f"  Successful       : "
        f"{successful}"
    )

    print(
        f"  Failed           : "
        f"{failures}"
    )

    print()
    print(
        "FILES"
    )

    print(
        f"  Discovery report:"
        f"\n    {DISCOVERY_REPORT.resolve()}"
    )

    print(
        f"  HTML report:"
        f"\n    {HTML_REPORT.resolve()}"
    )

    print(
        f"  State:"
        f"\n    {STATE_FILE.resolve()}"
    )

    print()
    print(
        "Archive:"
    )

    print(
        f"  {OUTPUT_DIR}"
    )

    print()
    print(
        "MP4 and ZIP files were not touched."
    )

    print(
        "HTML files were captured using absolute local destinations."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "Stopped by user."
        )

        print(
            "No cleanup/deletion operation was performed."
        )

        sys.exit(130)

    except Exception as exc:

        print()
        print(
            "=" * 78
        )

        print(
            "FATAL ERROR"
        )

        print(
            "=" * 78
        )

        print(
            str(exc)
        )

        sys.exit(1)