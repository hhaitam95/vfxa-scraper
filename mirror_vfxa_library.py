#!/usr/bin/env python3

"""
VFX Apprentice authenticated offline-library mirror.

WHAT THIS SCRIPT DOES
---------------------

1. Logs into VFX Apprentice using your local cookies.txt.
2. Crawls the authenticated /library hierarchy.
3. Discovers:
       Library
       Product
       Category
       Nested Category
       Lesson/Post
4. Saves every discovered page as HTML using SingleFile.
5. Saves product/category pages as index.html.
6. Saves lesson pages as "<Lesson Title>.html".
7. ALWAYS replaces existing HTML files.
8. NEVER overwrites existing MP4 or ZIP files.
9. Attempts to download missing MP4 videos.
10. Attempts to download lesson download resources.
11. HTML resources are replaced.
12. Other existing resources are preserved.
13. Shows live progress and ETA.
14. Writes CSV reports.
15. Saves state so an interrupted run can be inspected/restarted.

INTENTIONAL SCOPE
-----------------

Skipped:
    Beginner Bootcamp
    VFXA Free Training

Mirrored:
    VFX Apprentice Asset Library
    Hand-Drawn 2D FX: Level 1
    Hand-Drawn 2D FX: Level 2
    Hand-Crafted 3D VFX: Level 1
    Hand-Crafted 3D VFX: Level 2
    Apprenticeship Level 3

REQUIREMENTS
------------

- Python 3
- requests
- beautifulsoup4
- SingleFile CLI
- authenticated Netscape-format cookies.txt

No SingleFile settings JSON is required.
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
    unquote,
)

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.vfxapprentice.com"
LIBRARY_URL = f"{BASE_URL}/library"

# Your existing archive.
OUTPUT_DIR = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "vfx_apprentice_downloads"
)

# Your authenticated browser cookie export.
COOKIE_FILE = Path("cookies.txt")

# Reports.
HTML_REPORT = Path(
    "vfxa_html_download_report.csv"
)

RESOURCE_REPORT = Path(
    "vfxa_resource_download_report.csv"
)

DISCOVERY_REPORT = Path(
    "vfxa_library_tree.csv"
)

# Persistent discovery state.
STATE_FILE = Path(
    "vfxa_mirror_state.json"
)

# ------------------------------------------------------------
# PERFORMANCE
# ------------------------------------------------------------

# Number of SingleFile/Chrome processes running simultaneously.
#
# Recommended starting point for your Mac:
#     4
#
# Increase to 5-6 if CPU/RAM usage remains comfortable.
# Decrease to 2-3 if Chrome starts struggling.
SINGLEFILE_WORKERS = 4

# Requests used during hierarchy discovery / resource inspection.
REQUEST_WORKERS = 6

# Delay between ordinary HTTP requests.
REQUEST_DELAY = 0.5

# Delay before launching each SingleFile operation.
DOWNLOAD_DELAY = 0.25

# SingleFile waits.
#
# networkIdle is useful for pages which populate content dynamically.
# The additional delay is deliberately much shorter than the old 5 sec.
BROWSER_WAIT_UNTIL = "networkIdle"
BROWSER_WAIT_DELAY = "1000"

BROWSER_WIDTH = "1920"
BROWSER_HEIGHT = "1080"

# The products you explicitly said remain accessible after subscription.
SKIP_PRODUCTS = {
    "Beginner Bootcamp",
    "VFXA Free Training",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# ============================================================
# HELPERS
# ============================================================

def sanitize_name(name: str) -> str:
    """
    Convert a web title into a safe filename/folder name.
    """
    name = str(name).strip()

    name = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        name,
    )

    name = name.rstrip(" .")

    return name or "_unnamed"


def normalize_vfxa_url(url: str) -> str:
    """
    Convert a relative URL into an absolute VFXA URL and
    remove URL fragments.
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


def classify_url(url: str) -> str:
    """
    Identify VFXA page type.
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


def archive_relative(path: Path) -> str:
    """
    Convert an absolute archive path into a path relative to
    the archive root.
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
# COOKIE / SESSION FUNCTIONS
# ============================================================

def parse_cookies(
    cookie_file: Path,
) -> dict:
    """
    Parse a Netscape-format cookies.txt export.
    """
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

        for raw_line in f:

            line = raw_line.strip()

            if (
                not line
                or line.startswith("#")
            ):
                continue

            parts = line.split("\t")

            if len(parts) >= 7:

                name = parts[5].strip()
                value = parts[6].strip()

                if name:
                    cookies[name] = value

    if not cookies:
        raise RuntimeError(
            f"No usable cookies were found in:\n"
            f"{cookie_file}"
        )

    return cookies


def create_session(
    cookie_file: Path,
) -> requests.Session:

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
            cookie_file
        )
    )

    return session


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
    """
    One page in the VFX Apprentice hierarchy.
    """

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

    def local_path(
        self,
    ) -> Path:

        # ----------------------------------------------------
        # Library
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
        # Lesson
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
            f"Unknown node type: "
            f"{self.node_type}"
        )


# ============================================================
# HTML STRUCTURE EXTRACTION
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
# DISCOVERY
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
        "PHASE 1 — DISCOVERING LIBRARY TREE"
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

    queue = deque(
        [root]
    )

    queued = {
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

        print(
            f"[{len(nodes) + 1}] "
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

        # ----------------------------------------------------
        # Library
        # ----------------------------------------------------

        if node.node_type == "library":

            products = extract_products(
                BeautifulSoup(
                    html,
                    "html.parser",
                )
            )

            for title, url in products:

                if title in SKIP_PRODUCTS:
                    continue

                if url in queued:
                    continue

                queued.add(
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
        # Products/categories
        # ----------------------------------------------------

        elif node.node_type in {
            "product",
            "category",
        }:

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            categories, posts = (
                extract_categories_and_posts(
                    soup
                )
            )

            # ------------------------------------------------
            # Child categories
            # ------------------------------------------------

            for title, url in categories:

                if url in queued:
                    continue

                queued.add(
                    url
                )

                if node.node_type == "product":

                    child_path = []

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

                if url in queued:
                    continue

                queued.add(
                    url
                )

                if node.node_type == "product":

                    lesson_path = []

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
    print(
        f"Discovered {len(nodes)} pages."
    )

    type_counts = {}

    for node in nodes:

        type_counts[node.node_type] = (
            type_counts.get(
                node.node_type,
                0,
            )
            + 1
        )

    print(
        f"  Library   : "
        f"{type_counts.get('library', 0)}"
    )

    print(
        f"  Products  : "
        f"{type_counts.get('product', 0)}"
    )

    print(
        f"  Categories: "
        f"{type_counts.get('category', 0)}"
    )

    print(
        f"  Lessons   : "
        f"{type_counts.get('post', 0)}"
    )

    if errors:

        print()
        print(
            f"Discovery failures: "
            f"{len(errors)}"
        )

        for url, error in list(
            errors.items()
        )[:20]:

            print(
                f"  {error}: {url}"
            )

    return (
        nodes,
        errors,
    )


# ============================================================
# WRITE DISCOVERY REPORT
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
                "type": node.node_type,
                "title": node.title,
                "url": node.url,
                "parent_url": (
                    node.parent_url
                    or ""
                ),
                "local_path": archive_relative(
                    node.local_path()
                ),
                "status": "DISCOVERED",
            })

        for url, error in errors.items():

            writer.writerow({
                "type": classify_url(url),
                "title": "",
                "url": url,
                "parent_url": "",
                "local_path": "",
                "status": error,
            })


# ============================================================
# SINGLEFILE CAPTURE
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
            "Could not execute "
            "'single-file'."
        ) from exc

    if result.returncode != 0:

        raise RuntimeError(
            "SingleFile returned an error:\n"
            + (
                result.stderr.strip()
                or result.stdout.strip()
            )
        )

    print(
        "SingleFile:",
        result.stdout.strip(),
    )


def capture_one_html(
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

    command = [
        "single-file",

        "--browser-cookies-file",
        str(COOKIE_FILE),

        "--output-directory",
        str(target.parent),

        "--browser-width",
        BROWSER_WIDTH,

        "--browser-height",
        BROWSER_HEIGHT,

        "--browser-wait-until",
        BROWSER_WAIT_UNTIL,

        "--browser-wait-delay",
        BROWSER_WAIT_DELAY,

        # Explicitly overwrite existing HTML.
        "--filename-conflict-action",
        "overwrite",

        node.url,
        target.name,
    ]

    start = time.monotonic()

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
            "seconds": (
                time.monotonic()
                - start
            ),
            "error": str(exc),
        }

    elapsed = (
        time.monotonic()
        - start
    )

    if result.returncode != 0:

        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown SingleFile error"
        )

        return {
            "node": node,
            "status": "FAILED_SINGLEFILE",
            "size": 0,
            "seconds": elapsed,
            "error": error_text,
        }

    if not target.exists():

        return {
            "node": node,
            "status": "FAILED_OUTPUT_MISSING",
            "size": 0,
            "seconds": elapsed,
            "error": "",
        }

    size = target.stat().st_size

    if size == 0:

        return {
            "node": node,
            "status": "FAILED_OUTPUT_EMPTY",
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
# RESOURCE DETECTION
# ============================================================

def extract_wistia_id(
    html: str,
) -> Optional[str]:

    patterns = [
        r"wistia_async_([A-Za-z0-9]+)",
        r"embed/iframe/([A-Za-z0-9]+)",
        r"fast\.wistia\.com/embed/medias/([A-Za-z0-9]+)",
        r"fast\.wistia\.net/embed/medias/([A-Za-z0-9]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def extract_download_resources(
    soup: BeautifulSoup,
    source_url: str,
) -> list[dict]:

    resources = []
    seen = set()

    for link in soup.find_all(
        "a",
        class_="downloads-link",
        href=True,
    ):

        resource_url = urljoin(
            source_url,
            link["href"].strip(),
        )

        name_element = link.find(
            "div",
            class_="media-body",
        )

        if name_element:

            name = name_element.get_text(
                " ",
                strip=True,
            )

        else:

            name = link.get_text(
                " ",
                strip=True,
            )

        if (
            not resource_url
            or not name
        ):
            continue

        key = (
            name,
            resource_url,
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        resources.append({
            "name": name,
            "url": resource_url,
            "referer": source_url,
        })

    return resources


# ============================================================
# WISTIA MP4
# ============================================================

def resolve_wistia_mp4(
    session: requests.Session,
    wistia_id: str,
) -> Optional[dict]:

    url = (
        "https://fast.wistia.com/embed/medias/"
        f"{wistia_id}.json"
    )

    try:

        response = session.get(
            url,
            timeout=30,
        )

        if response.status_code != 200:
            return None

        data = response.json()

        assets = (
            data.get(
                "media",
                {},
            ).get(
                "assets",
                [],
            )
        )

        candidates = []

        for asset in assets:

            ext = str(
                asset.get(
                    "ext",
                    "",
                )
            ).lower()

            asset_type = str(
                asset.get(
                    "type",
                    "",
                )
            ).lower()

            media_url = asset.get(
                "url"
            )

            if not media_url:
                continue

            if (
                ext == "mp4"
                or "mp4" in asset_type
            ):
                candidates.append(
                    asset
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda asset: (
                asset.get(
                    "width",
                    0,
                ),
                asset.get(
                    "height",
                    0,
                ),
                asset.get(
                    "size",
                    0,
                ),
            ),
            reverse=True,
        )

        best = candidates[0]

        return {
            "url": best.get(
                "url"
            ),
            "width": best.get(
                "width",
                0,
            ),
            "height": best.get(
                "height",
                0,
            ),
            "size": best.get(
                "size",
                0,
            ),
        }

    except Exception:
        return None


# ============================================================
# RESOURCE FILENAMES
# ============================================================

def filename_from_content_disposition(
    header: Optional[str],
) -> Optional[str]:

    if not header:
        return None

    match = re.search(
        r"filename\*=UTF-8''([^;]+)",
        header,
        re.IGNORECASE,
    )

    if match:
        return sanitize_name(
            unquote(
                match.group(1)
            )
        )

    match = re.search(
        r'filename="?([^";]+)"?',
        header,
        re.IGNORECASE,
    )

    if match:
        return sanitize_name(
            match.group(1).strip()
        )

    return None


def resource_is_html(
    filename: str,
    response: requests.Response,
) -> bool:

    content_type = (
        response.headers.get(
            "content-type",
            "",
        )
        .lower()
    )

    if (
        "text/html"
        in content_type
        or "application/xhtml+xml"
        in content_type
    ):
        return True

    return (
        Path(filename)
        .suffix
        .lower()
        == ".html"
    )


def guess_resource_filename(
    name: str,
    response: requests.Response,
) -> str:

    header_filename = (
        filename_from_content_disposition(
            response.headers.get(
                "content-disposition"
            )
        )
    )

    if header_filename:
        return header_filename

    safe_name = sanitize_name(
        name
    )

    if Path(
        safe_name
    ).suffix:

        return safe_name

    final_suffix = Path(
        urlparse(
            response.url
        ).path
    ).suffix

    if final_suffix:
        return (
            safe_name
            + final_suffix
        )

    content_type = (
        response.headers.get(
            "content-type",
            "",
        )
        .lower()
    )

    mime_mapping = {
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
        "application/pdf": ".pdf",
        "application/rar": ".rar",
        "application/x-rar-compressed": ".rar",
        "application/x-7z-compressed": ".7z",
    }

    for mime, extension in (
        mime_mapping.items()
    ):

        if mime in content_type:

            return (
                safe_name
                + extension
            )

    # Historical behavior: unknown lesson
    # download resources are assumed to be ZIPs.
    return safe_name + ".zip"


# ============================================================
# RESOURCE DOWNLOAD
# ============================================================

def download_resource(
    session: requests.Session,
    resource: dict,
    target_dir: Path,
) -> dict:

    name = resource["name"]
    url = resource["url"]

    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if DOWNLOAD_DELAY > 0:
        time.sleep(
            DOWNLOAD_DELAY
        )

    headers = {
        "User-Agent": USER_AGENT,
    }

    referer = resource.get(
        "referer"
    )

    if referer:
        headers["Referer"] = referer

    try:

        with session.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=120,
        ) as response:

            if response.status_code != 200:

                return {
                    "status": (
                        "FAILED_HTTP_"
                        f"{response.status_code}"
                    ),
                    "local_path": "",
                    "size": 0,
                }

            filename = (
                guess_resource_filename(
                    name,
                    response,
                )
            )

            target = (
                target_dir
                / filename
            )

            suffix = (
                target.suffix.lower()
            )

            html_resource = (
                resource_is_html(
                    filename,
                    response,
                )
            )

            # ------------------------------------------------
            # EXISTING MP4:
            # ALWAYS SKIP
            # ------------------------------------------------

            if (
                suffix == ".mp4"
                and target.exists()
                and target.stat().st_size > 0
            ):

                return {
                    "status":
                        "ALREADY_EXISTS_MP4",
                    "local_path":
                        archive_relative(
                            target
                        ),
                    "size":
                        target.stat().st_size,
                }

            # ------------------------------------------------
            # EXISTING ZIP:
            # ALWAYS SKIP
            # ------------------------------------------------

            if (
                suffix == ".zip"
                and target.exists()
                and target.stat().st_size > 0
            ):

                return {
                    "status":
                        "ALREADY_EXISTS_ZIP",
                    "local_path":
                        archive_relative(
                            target
                        ),
                    "size":
                        target.stat().st_size,
                }

            # ------------------------------------------------
            # EXISTING HTML:
            # ALWAYS REPLACE
            # ------------------------------------------------

            replace_existing = (
                html_resource
            )

            # ------------------------------------------------
            # OTHER EXISTING FILE:
            # SKIP
            # ------------------------------------------------

            if (
                target.exists()
                and target.stat().st_size > 0
                and not replace_existing
            ):

                return {
                    "status":
                        "ALREADY_EXISTS",
                    "local_path":
                        archive_relative(
                            target
                        ),
                    "size":
                        target.stat().st_size,
                }

            # ------------------------------------------------
            # Download to .part first.
            # ------------------------------------------------

            temporary = (
                target.with_name(
                    target.name
                    + ".part"
                )
            )

            bytes_written = 0

            with temporary.open(
                "wb"
            ) as out:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:
                        out.write(
                            chunk
                        )

                        bytes_written += (
                            len(chunk)
                        )

            if bytes_written == 0:

                temporary.unlink(
                    missing_ok=True
                )

                return {
                    "status": "FAILED_EMPTY",
                    "local_path": "",
                    "size": 0,
                }

            temporary.replace(
                target
            )

            return {
                "status": (
                    "REPLACED_HTML"
                    if html_resource
                    else "DOWNLOADED"
                ),
                "local_path":
                    archive_relative(
                        target
                    ),
                "size":
                    bytes_written,
            }

    except requests.RequestException as exc:

        return {
            "status":
                "FAILED_REQUEST",
            "local_path": "",
            "size": 0,
            "error": str(exc),
        }


# ============================================================
# LESSON RESOURCE PROCESSING
# ============================================================

def inspect_lesson(
    session: requests.Session,
    node: Node,
    page_html: str,
) -> list[dict]:

    rows = []

    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    # --------------------------------------------------------
    # MP4
    # --------------------------------------------------------

    wistia_id = extract_wistia_id(
        page_html
    )

    if wistia_id:

        mp4_info = resolve_wistia_mp4(
            session,
            wistia_id,
        )

        target_mp4 = (
            node.local_path().parent
            / (
                sanitize_name(
                    node.title
                )
                + ".mp4"
            )
        )

        if target_mp4.exists() and (
            target_mp4.stat().st_size > 0
        ):

            rows.append({
                "type": "video",
                "lesson": node.title,
                "url": (
                    mp4_info["url"]
                    if mp4_info
                    else ""
                ),
                "name": target_mp4.name,
                "local_path":
                    archive_relative(
                        target_mp4
                    ),
                "status":
                    "ALREADY_EXISTS_MP4",
                "size_bytes":
                    target_mp4.stat().st_size,
            })

        elif not mp4_info:

            rows.append({
                "type": "video",
                "lesson": node.title,
                "url": "",
                "name": (
                    sanitize_name(
                        node.title
                    )
                    + ".mp4"
                ),
                "local_path": "",
                "status":
                    "WISTIA_NOT_RESOLVED",
                "size_bytes": 0,
            })

        else:

            result = download_video(
                session,
                node,
                mp4_info,
            )

            rows.append({
                "type": "video",
                "lesson": node.title,
                "url": mp4_info["url"],
                "name": target_mp4.name,
                "local_path":
                    result["local_path"],
                "status":
                    result["status"],
                "size_bytes":
                    result["size"],
            })

    # --------------------------------------------------------
    # Explicit lesson downloads
    # --------------------------------------------------------

    resources = (
        extract_download_resources(
            soup,
            node.url,
        )
    )

    for resource in resources:

        result = download_resource(
            session,
            resource,
            node.local_path().parent,
        )

        rows.append({
            "type": "resource",
            "lesson": node.title,
            "url": resource["url"],
            "name": resource["name"],
            "local_path":
                result.get(
                    "local_path",
                    "",
                ),
            "status":
                result.get(
                    "status",
                    "UNKNOWN",
                ),
            "size_bytes":
                result.get(
                    "size",
                    0,
                ),
        })

    return rows


# ============================================================
# VIDEO DOWNLOAD
# ============================================================

def download_video(
    session: requests.Session,
    node: Node,
    mp4_info: dict,
) -> dict:

    target = (
        node.local_path().parent
        / (
            sanitize_name(
                node.title
            )
            + ".mp4"
        )
    )

    # Existing MP4 is protected.
    if (
        target.exists()
        and target.stat().st_size > 0
    ):

        return {
            "status":
                "ALREADY_EXISTS_MP4",
            "local_path":
                archive_relative(
                    target
                ),
            "size":
                target.stat().st_size,
        }

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if DOWNLOAD_DELAY > 0:
        time.sleep(
            DOWNLOAD_DELAY
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": node.url,
    }

    try:

        with session.get(
            mp4_info["url"],
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=120,
        ) as response:

            if response.status_code != 200:

                return {
                    "status":
                        "FAILED_HTTP_"
                        f"{response.status_code}",
                    "local_path": "",
                    "size": 0,
                }

            temporary = target.with_name(
                target.name
                + ".part"
            )

            bytes_written = 0

            with temporary.open(
                "wb"
            ) as out:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:
                        out.write(
                            chunk
                        )

                        bytes_written += (
                            len(chunk)
                        )

            if bytes_written == 0:

                temporary.unlink(
                    missing_ok=True
                )

                return {
                    "status":
                        "FAILED_EMPTY",
                    "local_path": "",
                    "size": 0,
                }

            temporary.replace(
                target
            )

            return {
                "status":
                    "DOWNLOADED_MP4",
                "local_path":
                    archive_relative(
                        target
                    ),
                "size":
                    bytes_written,
            }

    except requests.RequestException as exc:

        return {
            "status":
                "FAILED_REQUEST",
            "local_path": "",
            "size": 0,
            "error": str(exc),
        }


# ============================================================
# STATE
# ============================================================

def load_state() -> dict:

    if not STATE_FILE.exists():

        return {
            "last_run": None,
            "pages": {},
        }

    try:

        with STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:

            state = json.load(
                f
            )

        if not isinstance(
            state,
            dict,
        ):
            raise ValueError

        state.setdefault(
            "pages",
            {}
        )

        return state

    except Exception:

        print(
            "WARNING: Could not read state file."
        )

        return {
            "last_run": None,
            "pages": {},
        }


def save_state(
    state: dict,
) -> None:

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
# HTML CAPTURE BATCH
# ============================================================

def capture_all_html(
    nodes: list[Node],
) -> list[dict]:

    print()
    print("=" * 78)
    print(
        "PHASE 2 — CAPTURING HTML WITH SINGLEFILE"
    )
    print("=" * 78)

    total = len(nodes)

    results = []

    completed = 0
    failed = 0

    start_time = time.monotonic()
    durations = []

    print()
    print(
        f"Pages to capture: {total}"
    )

    print(
        f"Parallel SingleFile workers: "
        f"{SINGLEFILE_WORKERS}"
    )

    print(
        f"Browser wait: "
        f"{BROWSER_WAIT_UNTIL}"
        f" + {BROWSER_WAIT_DELAY} ms"
    )

    print()

    with ThreadPoolExecutor(
        max_workers=SINGLEFILE_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                capture_one_html,
                node,
            ): node
            for node in nodes
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

            except Exception as exc:

                node = futures[
                    future
                ]

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

            if result["seconds"] > 0:
                durations.append(
                    result["seconds"]
                )

            if result[
                "status"
            ].startswith("FAILED"):

                failed += 1

            # ------------------------------------------------
            # ETA
            # ------------------------------------------------

            elapsed = (
                time.monotonic()
                - start_time
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

            node = result["node"]

            if result["status"].startswith(
                "FAILED"
            ):
                marker = "FAILED"

            elif result["status"] == "REPLACED":
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
                    f"Rate: {rate:.2f} pages/sec | "
                    f"ETA: {eta_minutes:.1f} min"
                )

            if result.get(
                "error"
            ) and result[
                "status"
            ].startswith("FAILED"):

                print(
                    f"          "
                    f"{result['error'][:300]}"
                )

    total_elapsed = (
        time.monotonic()
        - start_time
    )

    print()
    print(
        "HTML capture finished."
    )

    print(
        f"Elapsed: "
        f"{total_elapsed / 60:.1f} minutes"
    )

    if total_elapsed > 0:

        print(
            f"Average: "
            f"{total / total_elapsed:.2f} "
            f"pages/sec"
        )

    print(
        f"Failures: {failed}"
    )

    return results


# ============================================================
# RESOURCE BATCH
# ============================================================

def audit_and_download_resources(
    session: requests.Session,
    nodes: list[Node],
) -> list[dict]:

    post_nodes = [
        node
        for node in nodes
        if node.node_type == "post"
    ]

    print()
    print("=" * 78)
    print(
        "PHASE 3 — AUDITING LESSON VIDEOS / RESOURCES"
    )
    print("=" * 78)

    print()
    print(
        f"Lesson pages to inspect: "
        f"{len(post_nodes)}"
    )

    rows = []

    completed = 0

    start_time = time.monotonic()

    # --------------------------------------------------------
    # Fetch lessons concurrently.
    # --------------------------------------------------------

    def inspect_one(
        node: Node,
    ) -> list[dict]:

        page_html, status = fetch_page(
            session,
            node.url,
        )

        if page_html is None:

            return [{
                "type": "lesson",
                "lesson": node.title,
                "url": node.url,
                "name": "",
                "local_path": "",
                "status": (
                    "FAILED_PAGE_"
                    f"{status or 'REQUEST_ERROR'}"
                ),
                "size_bytes": 0,
            }]

        return inspect_lesson(
            session,
            node,
            page_html,
        )

    with ThreadPoolExecutor(
        max_workers=REQUEST_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                inspect_one,
                node,
            ): node
            for node in post_nodes
        }

        for future in as_completed(
            futures
        ):

            node = futures[
                future
            ]

            try:

                result_rows = (
                    future.result()
                )

            except Exception as exc:

                result_rows = [{
                    "type": "lesson",
                    "lesson": node.title,
                    "url": node.url,
                    "name": "",
                    "local_path": "",
                    "status":
                        "FAILED_EXCEPTION",
                    "size_bytes": 0,
                    "error": str(exc),
                }]

            rows.extend(
                result_rows
            )

            completed += 1

            elapsed = (
                time.monotonic()
                - start_time
            )

            if elapsed > 0:

                rate = (
                    completed
                    / elapsed
                )

                remaining = (
                    len(post_nodes)
                    - completed
                )

                eta_seconds = (
                    remaining / rate
                    if rate > 0
                    else 0
                )

                print(
                    f"[{completed:4d}/"
                    f"{len(post_nodes)}] "
                    f"Resources: "
                    f"{node.title[:55]}"
                )

                if completed >= 5:

                    print(
                        f"          "
                        f"Rate: "
                        f"{rate:.2f} lessons/sec | "
                        f"ETA: "
                        f"{eta_seconds / 60:.1f} min"
                    )

    return rows


# ============================================================
# REPORTS
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


def write_resource_report(
    rows: list[dict],
) -> None:

    with RESOURCE_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        fields = [
            "type",
            "lesson",
            "url",
            "name",
            "local_path",
            "status",
            "size_bytes",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for row in rows:

            writer.writerow({
                field:
                    row.get(
                        field,
                        "",
                    )
                for field in fields
            })


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE OFFLINE LIBRARY MIRROR"
    )
    print("=" * 78)

    print()
    print(
        "Scope:"
    )

    for product in sorted(
        SKIP_PRODUCTS
    ):
        print(
            f"  SKIP: {product}"
        )

    print()
    print(
        f"Archive: {OUTPUT_DIR}"
    )

    print(
        f"Cookies: {COOKIE_FILE}"
    )

    print()
    print(
        "HTML policy:"
    )

    print(
        "  Existing HTML → REPLACE"
    )

    print(
        "  Existing MP4  → SKIP"
    )

    print(
        "  Existing ZIP   → SKIP"
    )

    print()
    print(
        "Performance:"
    )

    print(
        f"  SingleFile workers: "
        f"{SINGLEFILE_WORKERS}"
    )

    print(
        f"  Request workers: "
        f"{REQUEST_WORKERS}"
    )

    print(
        f"  SingleFile wait: "
        f"{BROWSER_WAIT_DELAY} ms"
    )

    # --------------------------------------------------------
    # Setup
    # --------------------------------------------------------

    if not COOKIE_FILE.exists():

        raise FileNotFoundError(
            f"\nMissing cookies file:\n"
            f"{COOKIE_FILE}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    verify_singlefile()

    session = create_session(
        COOKIE_FILE
    )

    state = load_state()

    # --------------------------------------------------------
    # Phase 1
    # --------------------------------------------------------

    nodes, discovery_errors = (
        discover_tree(
            session
        )
    )

    if not nodes:

        raise RuntimeError(
            "\nNo authenticated pages were discovered."
        )

    write_discovery_report(
        nodes,
        discovery_errors,
    )

    # --------------------------------------------------------
    # Phase 2
    # --------------------------------------------------------

    html_results = capture_all_html(
        nodes
    )

    # --------------------------------------------------------
    # Phase 3
    # --------------------------------------------------------

    resource_rows = (
        audit_and_download_resources(
            session,
            nodes,
        )
    )

    # --------------------------------------------------------
    # Reports
    # --------------------------------------------------------

    write_html_report(
        html_results
    )

    write_resource_report(
        resource_rows
    )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state[
        "last_run"
    ] = time.time()

    state[
        "pages"
    ] = {}

    for result in html_results:

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
            "timestamp":
                time.time(),
        }

    save_state(
        state
    )

    # --------------------------------------------------------
    # Final statistics
    # --------------------------------------------------------

    html_success = sum(
        1
        for result in html_results
        if not result[
            "status"
        ].startswith("FAILED")
    )

    html_failed = sum(
        1
        for result in html_results
        if result[
            "status"
        ].startswith("FAILED")
    )

    mp4_downloaded = sum(
        1
        for row in resource_rows
        if row["status"]
        == "DOWNLOADED_MP4"
    )

    mp4_existing = sum(
        1
        for row in resource_rows
        if row["status"]
        == "ALREADY_EXISTS_MP4"
    )

    zip_existing = sum(
        1
        for row in resource_rows
        if row["status"]
        == "ALREADY_EXISTS_ZIP"
    )

    resources_downloaded = sum(
        1
        for row in resource_rows
        if row["status"]
        in {
            "DOWNLOADED",
            "REPLACED_HTML",
        }
    )

    resources_html_replaced = sum(
        1
        for row in resource_rows
        if row["status"]
        == "REPLACED_HTML"
    )

    resources_failed = sum(
        1
        for row in resource_rows
        if row["status"].startswith(
            "FAILED"
        )
        or row["status"]
        == "WISTIA_NOT_RESOLVED"
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "FINAL SUMMARY"
    )
    print("=" * 78)

    print()
    print(
        "PAGE TREE"
    )

    print(
        f"  Pages discovered : "
        f"{len(nodes)}"
    )

    print(
        f"  Discovery errors : "
        f"{len(discovery_errors)}"
    )

    print()
    print(
        "HTML"
    )

    print(
        f"  Successful       : "
        f"{html_success}"
    )

    print(
        f"  Failed           : "
        f"{html_failed}"
    )

    print()
    print(
        "VIDEOS"
    )

    print(
        f"  MP4 downloaded   : "
        f"{mp4_downloaded}"
    )

    print(
        f"  MP4 already had  : "
        f"{mp4_existing}"
    )

    print()
    print(
        "RESOURCES"
    )

    print(
        f"  Resources downloaded/replaced:"
        f" {resources_downloaded}"
    )

    print(
        f"  HTML resources replaced:"
        f" {resources_html_replaced}"
    )

    print(
        f"  ZIPs already present:"
        f" {zip_existing}"
    )

    print(
        f"  Failed/unresolved:"
        f" {resources_failed}"
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
        f"  Resource report:"
        f"\n    {RESOURCE_REPORT.resolve()}"
    )

    print(
        f"  State:"
        f"\n    {STATE_FILE.resolve()}"
    )

    print()
    print(
        "Existing MP4 and ZIP files were not overwritten."
    )

    print(
        "Existing HTML pages were refreshed."
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
            "Existing files were not deleted."
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