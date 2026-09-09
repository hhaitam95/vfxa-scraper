#!/usr/bin/env python3

"""
VFX Apprentice HTML Mirror - PATH VALIDATION TEST

This test deliberately downloads ONLY FIVE HTML pages:

1. Main Library
2. One Product
3. One Category
4. One Nested Category
5. One Lesson/Post

Purpose:
    Verify that the VFX Apprentice hierarchy is mapped to the correct
    local folders before running the full 692-page mirror.

IMPORTANT:
    - Only HTML files are downloaded.
    - Existing HTML files are overwritten.
    - MP4 files are NEVER touched.
    - ZIP files are NEVER touched.
    - No resources are downloaded.
    - No files are deleted.
"""

import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.vfxapprentice.com"
LIBRARY_URL = f"{BASE_URL}/library"

# YOUR CORRECT ARCHIVE LOCATION
OUTPUT_DIR = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

COOKIE_FILE = Path("cookies.txt")

# Products that remain accessible to you.
SKIP_PRODUCTS = {
    "Beginner Bootcamp",
    "VFXA Free Training",
}

# SingleFile settings
BROWSER_WIDTH = "1920"
BROWSER_HEIGHT = "1080"
BROWSER_WAIT_UNTIL = "networkIdle"
BROWSER_WAIT_DELAY = "1000"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

REQUEST_DELAY = 0.5
SINGLEFILE_DELAY = 0.5


# ============================================================
# HELPERS
# ============================================================

def sanitize_name(name: str) -> str:
    """Convert website title into a safe local filename/folder name."""
    name = str(name).strip()

    name = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        name,
    )

    return name.rstrip(" .") or "_unnamed"


def normalize_url(url: str) -> str:
    """Make a VFXA URL absolute and remove fragments."""
    if not url:
        return ""

    url = urljoin(
        BASE_URL,
        url,
    )

    parsed = urlparse(url)

    if parsed.netloc.lower() not in {
        "www.vfxapprentice.com",
        "vfxapprentice.com",
    }:
        return ""

    parsed = parsed._replace(
        fragment=""
    )

    return urlunparse(parsed)


def classify_url(url: str) -> str:
    """Classify a VFXA URL."""

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


def parse_cookies(
    cookie_file: Path,
) -> dict:

    if not cookie_file.exists():
        raise FileNotFoundError(
            f"Cookie file not found:\n{cookie_file}"
        )

    cookies = {}

    with cookie_file.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:

        for line in f:

            line = line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")

            if len(parts) >= 7:

                name = parts[5].strip()
                value = parts[6].strip()

                if name:
                    cookies[name] = value

    if not cookies:
        raise RuntimeError(
            "No usable cookies were found."
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
        "Accept-Language": "en-US,en;q=0.9",
    })

    session.cookies.update(
        parse_cookies(
            COOKIE_FILE
        )
    )

    return session


def fetch(
    session: requests.Session,
    url: str,
) -> Optional[str]:

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

            print(
                f"  HTTP {response.status_code}: {url}"
            )

            return None

        return response.text

    except requests.RequestException as exc:

        print(
            f"  Request failed: {url}"
        )

        print(
            f"  {exc}"
        )

        return None


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

            return (
                OUTPUT_DIR
                / product_folder
                / Path(*folders)
                / (
                    sanitize_name(
                        self.title
                    )
                    + ".html"
                )
            )

        raise ValueError(
            f"Unknown node type: "
            f"{self.node_type}"
        )


# ============================================================
# DISCOVERY HELPERS
# ============================================================

def extract_products(
    soup: BeautifulSoup,
):

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

        url = normalize_url(
            link_element["href"]
        )

        if not url:
            continue

        if classify_url(url) != "product":
            continue

        if title in SKIP_PRODUCTS:
            continue

        pair = (
            title,
            url,
        )

        if pair not in seen:

            seen.add(
                pair
            )

            results.append(
                pair
            )

    return results


def extract_children(
    soup: BeautifulSoup,
):

    categories = []
    posts = []

    seen_categories = set()
    seen_posts = set()

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

        if not link or not title:
            continue

        title_text = title.get_text(
            " ",
            strip=True,
        )

        url = normalize_url(
            link["href"]
        )

        if (
            not url
            or classify_url(url)
            != "category"
        ):
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

        if not link or not title:
            continue

        title_text = title.get_text(
            " ",
            strip=True,
        )

        url = normalize_url(
            link["href"]
        )

        if (
            not url
            or classify_url(url)
            != "post"
        ):
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
# DISCOVER A REPRESENTATIVE TREE
# ============================================================

def discover_test_nodes(
    session: requests.Session,
):

    print()
    print("=" * 78)
    print(
        "DISCOVERING TEST PAGES"
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

    visited = set()

    library_node = root
    product_node = None
    category_node = None
    nested_category_node = None
    post_node = None

    while queue and (
        post_node is None
    ):

        node = queue.popleft()

        if node.url in visited:
            continue

        visited.add(
            node.url
        )

        html = fetch(
            session,
            node.url,
        )

        if html is None:
            continue

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        # ----------------------------------------------------
        # Product selection
        # ----------------------------------------------------

        if node.node_type == "library":

            products = extract_products(
                soup
            )

            if products:

                title, url = products[0]

                product_node = Node(
                    url=url,
                    node_type="product",
                    title=title,
                    product_name=title,
                    path_parts=[],
                    parent_url=node.url,
                )

                queue.append(
                    product_node
                )

        # ----------------------------------------------------
        # Category + Post selection
        # ----------------------------------------------------

        elif node.node_type in {
            "product",
            "category",
        }:

            categories, posts = (
                extract_children(
                    soup
                )
            )

            # ------------------------------------------------
            # First available post.
            #
            # If the current node is a category, this gives
            # us a proper lesson beneath that category.
            # ------------------------------------------------

            if (
                node.node_type == "category"
                and posts
                and post_node is None
            ):

                title, url = posts[0]

                post_node = Node(
                    url=url,
                    node_type="post",
                    title=title,
                    product_name=node.product_name,
                    path_parts=(
                        list(node.path_parts)
                        + [node.title]
                    ),
                    parent_url=node.url,
                )

            # ------------------------------------------------
            # Add children.
            # ------------------------------------------------

            for title, url in categories:

                child_path = (
                    []
                    if node.node_type
                    == "product"
                    else (
                        list(
                            node.path_parts
                        )
                        + [node.title]
                    )
                )

                child = Node(
                    url=url,
                    node_type="category",
                    title=title,
                    product_name=node.product_name,
                    path_parts=child_path,
                    parent_url=node.url,
                )

                # First category under product.
                if (
                    node.node_type
                    == "product"
                    and category_node
                    is None
                ):

                    category_node = child

                # First child category under category.
                elif (
                    node.node_type
                    == "category"
                    and nested_category_node
                    is None
                ):

                    nested_category_node = child

                queue.append(
                    child
                )

    # --------------------------------------------------------
    # We specifically want a nested category. If we don't
    # have one yet, walk the selected category.
    # --------------------------------------------------------

    if (
        category_node
        and nested_category_node is None
    ):

        html = fetch(
            session,
            category_node.url,
        )

        if html:

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            categories, posts = (
                extract_children(
                    soup
                )
            )

            if categories:

                title, url = categories[0]

                nested_category_node = Node(
                    url=url,
                    node_type="category",
                    title=title,
                    product_name=category_node.product_name,
                    path_parts=[
                        category_node.title
                    ],
                    parent_url=category_node.url,
                )

            if (
                posts
                and post_node is None
            ):

                title, url = posts[0]

                post_node = Node(
                    url=url,
                    node_type="post",
                    title=title,
                    product_name=category_node.product_name,
                    path_parts=[
                        category_node.title
                    ],
                    parent_url=category_node.url,
                )

    # --------------------------------------------------------
    # If nested category exists, get a lesson under it.
    # --------------------------------------------------------

    if nested_category_node:

        html = fetch(
            session,
            nested_category_node.url,
        )

        if html:

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            _, posts = extract_children(
                soup
            )

            if posts:

                title, url = posts[0]

                post_node = Node(
                    url=url,
                    node_type="post",
                    title=title,
                    product_name=(
                        nested_category_node.product_name
                    ),
                    path_parts=[
                        *nested_category_node.path_parts,
                        nested_category_node.title,
                    ],
                    parent_url=(
                        nested_category_node.url
                    ),
                )

    test_nodes = [
        library_node,
        product_node,
        category_node,
        nested_category_node,
        post_node,
    ]

    test_nodes = [
        node
        for node in test_nodes
        if node is not None
    ]

    return test_nodes


# ============================================================
# SINGLEFILE
# ============================================================

def verify_singlefile():

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
            "SingleFile returned an error:\n"
            + (
                result.stderr.strip()
                or result.stdout.strip()
            )
        )

    print(
        f"SingleFile: "
        f"{result.stdout.strip()}"
    )


def capture_test_page(
    node: Node,
):

    target = node.local_path()

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print(
        "-" * 78
    )

    print(
        f"TYPE : {node.node_type}"
    )

    print(
        f"TITLE: {node.title}"
    )

    print(
        f"URL  : {node.url}"
    )

    print(
        f"PATH : {target}"
    )

    if SINGLEFILE_DELAY > 0:
        time.sleep(
            SINGLEFILE_DELAY
        )

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

        "--filename-conflict-action",
        "overwrite",

        # IMPORTANT:
        # Give SingleFile the COMPLETE destination path.
        node.url,
        str(target),
    ]

    start = time.monotonic()

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    elapsed = (
        time.monotonic()
        - start
    )

    if result.returncode != 0:

        print()
        print(
            "FAILED"
        )

        if result.stderr.strip():
            print(
                result.stderr.strip()
            )

        return False

    if not target.exists():

        print(
            "FAILED: output file was not created."
        )

        return False

    size = target.stat().st_size

    if size == 0:

        print(
            "FAILED: output file is empty."
        )

        return False

    print(
        f"SUCCESS — "
        f"{size / 1024 / 1024:.2f} MB "
        f"in {elapsed:.1f}s"
    )

    return True


# ============================================================
# FINAL VALIDATION
# ============================================================

def validate_results(
    nodes,
):

    print()
    print("=" * 78)
    print(
        "VALIDATING TEST FILES"
    )
    print("=" * 78)

    passed = True

    for node in nodes:

        target = node.local_path()

        exists = (
            target.exists()
            and target.stat().st_size > 0
        )

        print()

        print(
            f"{'PASS' if exists else 'FAIL':4} "
            f"{node.node_type:8} "
            f"{target}"
        )

        if not exists:
            passed = False

    print()

    if passed:

        print(
            "TEST PASSED."
        )

        print()
        print(
            "All representative HTML pages were "
            "written to their intended hierarchy."
        )

    else:

        print(
            "TEST FAILED."
        )

    return passed


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE HTML PATH VALIDATION TEST"
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
        "This test will create ONLY HTML files."
    )

    print(
        "Existing HTML will be replaced."
    )

    print(
        "MP4/ZIP files will NOT be touched."
    )

    print()

    if not OUTPUT_DIR.exists():

        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    if not COOKIE_FILE.exists():

        raise FileNotFoundError(
            f"Missing:\n{COOKIE_FILE}"
        )

    verify_singlefile()

    session = create_session()

    # --------------------------------------------------------
    # Discover representative pages
    # --------------------------------------------------------

    nodes = discover_test_nodes(
        session
    )

    if len(nodes) < 3:

        raise RuntimeError(
            "Could not discover enough representative "
            "pages to perform the test."
        )

    # --------------------------------------------------------
    # Display planned paths BEFORE downloading
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "PLANNED LOCAL DESTINATIONS"
    )
    print("=" * 78)

    for index, node in enumerate(
        nodes,
        start=1,
    ):

        print()
        print(
            f"{index}. {node.node_type.upper()}"
        )

        print(
            f"   {node.title}"
        )

        print(
            f"   {node.url}"
        )

        print(
            f"   -> {node.local_path()}"
        )

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "CAPTURING TEST PAGES"
    )
    print("=" * 78)

    success = 0

    for node in nodes:

        if capture_test_page(
            node
        ):

            success += 1

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    passed = validate_results(
        nodes
    )

    print()
    print("=" * 78)

    print(
        f"Successful captures: "
        f"{success}/{len(nodes)}"
    )

    print(
        f"Archive: "
        f"{OUTPUT_DIR}"
    )

    print("=" * 78)

    if not passed:
        sys.exit(1)


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print()
        print(
            "Test cancelled."
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