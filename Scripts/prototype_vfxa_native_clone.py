#!/usr/bin/env python3

"""
VFX Apprentice — Browser-Capture Native Offline Prototype

TEST PAGE
---------
Composition (Staging)

SOURCE:
    0187a231-bab4-43ad-9f3a-cb2281e0cf79.html

This is the browser-extension SingleFile capture.

GOAL
----
Keep the original VFX Apprentice page appearance and DOM as much
as possible, while making the page actually usable offline.

CHANGES:
    1. Preserve original VFXA HTML/CSS.
    2. Rewrite known internal VFXA lesson/category/library links
       to local files.
    3. Replace the Wistia player with a native HTML5 <video>
       pointing at the existing local MP4.
    4. Leave all other content untouched.
    5. Write a NEW .offline.html file.

DOES NOT:
    - download anything
    - contact VFX Apprentice
    - modify the original HTML
    - modify MP4 files
    - modify ZIP files
"""


from pathlib import Path
from urllib.parse import urljoin, urlparse
from html import escape
import re
import unicodedata

from bs4 import BeautifulSoup, Comment

# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = Path.cwd()

ARCHIVE_ROOT = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

SOURCE_HTML = (
    SCRIPT_DIR
    / "0187a231-bab4-43ad-9f3a-cb2281e0cf79.html"
)

OUTPUT_HTML = (
    SCRIPT_DIR
    / "0187a231-bab4-43ad-9f3a-cb2281e0cf79.offline.html"
)

LOCAL_VIDEO = (
    ARCHIVE_ROOT
    / "Hand-Drawn 2D FX_ Level 1"
    / "FX Design Principles - Explained"
    / "Composition (Staging).mp4"
)

# Known local pages for this test.
LOCAL_LIBRARY = (
    ARCHIVE_ROOT
    / "index.html"
)

LOCAL_PRODUCT = (
    ARCHIVE_ROOT
    / "Hand-Drawn 2D FX_ Level 1"
    / "index.html"
)

LOCAL_CATEGORY = (
    ARCHIVE_ROOT
    / "Hand-Drawn 2D FX_ Level 1"
    / "FX Design Principles - Explained"
    / "index.html"
)

LOCAL_LESSON = (
    ARCHIVE_ROOT
    / "Hand-Drawn 2D FX_ Level 1"
    / "FX Design Principles - Explained"
    / "Composition (Staging).html"
)


SOURCE_URL = (
    "https://www.vfxapprentice.com/"
    "products/hand-drawn-2d-fx-level-1/"
    "categories/2150627140/posts/2158959461"
)

LIBRARY_URLS = {
    "https://www.vfxapprentice.com/library":
        LOCAL_LIBRARY,

    "https://www.vfxapprentice.com/library/":
        LOCAL_LIBRARY,

    "https://www.vfxapprentice.com/products/"
    "hand-drawn-2d-fx-level-1":
        LOCAL_PRODUCT,

    "https://www.vfxapprentice.com/products/"
    "hand-drawn-2d-fx-level-1/":
        LOCAL_PRODUCT,

    "https://www.vfxapprentice.com/products/"
    "hand-drawn-2d-fx-level-1/categories/2150627140":
        LOCAL_CATEGORY,

    "https://www.vfxapprentice.com/products/"
    "hand-drawn-2d-fx-level-1/categories/2150627140/":
        LOCAL_CATEGORY,

    SOURCE_URL:
        LOCAL_LESSON,

    SOURCE_URL + "/":
        LOCAL_LESSON,
}


# ============================================================
# HELPERS
# ============================================================

def normalize_text(value: str) -> str:

    return unicodedata.normalize(
        "NFC",
        str(value).strip(),
    )


def normalize_url(value: str) -> str:

    if not value:
        return ""

    absolute = urljoin(
        SOURCE_URL,
        value,
    )

    parsed = urlparse(
        absolute
    )

    if parsed.netloc.lower() not in {
        "www.vfxapprentice.com",
        "vfxapprentice.com",
    }:

        return ""

    path = parsed.path

    if path != "/":
        path = path.rstrip("/")

    return (
        "https://www.vfxapprentice.com"
        + path
    )


def relative_link(
    current_file: Path,
    target_file: Path,
) -> str:

    import os

    return os.path.relpath(
        target_file,
        current_file.parent,
    )


# ============================================================
# VIDEO PLAYER
# ============================================================

def replace_wistia_player(
    soup: BeautifulSoup,
    video_path: Path,
):

    """
    Find the rendered Wistia player and replace only that player
    with a native HTML5 video element.

    We try several selectors because SingleFile captures can have
    slightly different Wistia wrappers.
    """

    selectors = [
        ".wistia_embed",
        ".wistia_responsive_padding",
        ".wistia_responsive_wrapper",
        ".w-css-reset",
    ]

    player = None

    for selector in selectors:

        candidate = soup.select_one(
            selector
        )

        if candidate:

            player = candidate
            break

    if player is None:

        # Fallback: search by Wistia-related classes.
        for element in soup.find_all(
            class_=True
        ):

            classes = " ".join(
                element.get("class", [])
            ).lower()

            if (
                "wistia" in classes
                and (
                    "embed" in classes
                    or "player" in classes
                    or "responsive" in classes
                )
            ):

                player = element
                break

    if player is None:

        return False, "Wistia player container not found"

    source = soup.new_tag(
        "source"
    )

    video_href = relative_link(
        OUTPUT_HTML,
        video_path,
    )

    source["src"] = video_href
    source["type"] = "video/mp4"

    video = soup.new_tag(
        "video"
    )

    video["controls"] = True
    video["preload"] = "metadata"
    video["playsinline"] = True

    video["style"] = (
        "width:100%;"
        "height:auto;"
        "display:block;"
        "background:#000;"
    )

    video.append(
        source
    )

    fallback = soup.new_string(
        "Your browser does not support HTML5 video."
    )

    video.append(
        fallback
    )

    # Preserve the overall visual footprint.
    wrapper = soup.new_tag(
        "div"
    )

    wrapper["class"] = (
        player.get("class", [])
        + ["vfxa-offline-video"]
    )

    wrapper["style"] = (
        "width:100%;"
        "background:#000;"
    )

    wrapper.append(
        video
    )

    player.replace_with(
        wrapper
    )

    return True, "Wistia player replaced"


# ============================================================
# LINK REWRITING
# ============================================================

def rewrite_internal_links(
    soup: BeautifulSoup,
):

    rewritten = 0
    unmapped = 0
    internal = 0

    # Work on anchors and link elements.
    for element in soup.find_all(
        ["a", "link"],
        href=True,
    ):

        href = element.get(
            "href",
            "",
        ).strip()

        if not href:
            continue

        if href.startswith(
            (
                "#",
                "mailto:",
                "tel:",
                "javascript:",
                "data:",
            )
        ):
            continue

        normalized = normalize_url(
            href
        )

        if not normalized:
            continue

        # Only exact known pages for this prototype.
        if normalized in LIBRARY_URLS:

            target = LIBRARY_URLS[
                normalized
            ]

            if not target.exists():

                unmapped += 1
                continue

            fragment = ""

            parsed = urlparse(
                href
            )

            if parsed.fragment:

                fragment = (
                    "#"
                    + parsed.fragment
                )

            relative = relative_link(
                OUTPUT_HTML,
                target,
            )

            element[
                "href"
            ] = relative + fragment

            rewritten += 1

        else:

            # It's an internal VFXA URL but we don't have a
            # mapping for it yet.
            if normalized.startswith(
                "https://www.vfxapprentice.com/"
            ):

                internal += 1

                # Don't change it yet.
                unmapped += 1

    return (
        rewritten,
        unmapped,
        internal,
    )


# ============================================================
# CLEAN ONLINE-ONLY WIDGETS
# ============================================================

def disable_online_only_elements(
    soup: BeautifulSoup,
):

    """
    Do not destroy the VFXA look.

    Only disable obvious actions that cannot work offline.
    """

    disabled = 0

    for element in soup.find_all(
        ["a", "button"]
    ):

        text = element.get_text(
            " ",
            strip=True,
        ).casefold()

        href = element.get(
            "href",
            "",
        )

        # Leave normal lesson navigation alone.
        if not (
            "mark complete" in text
            or "lesson survey" in text
            or "logout" in text
        ):
            continue

        if element.name == "a":

            if href:
                element[
                    "href"
                ] = "#"

            element[
                "onclick"
            ] = (
                "return false;"
            )

        else:

            element[
                "disabled"
            ] = True

        disabled += 1

    return disabled


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE — NATIVE OFFLINE PAGE PROTOTYPE"
    )
    print("=" * 78)

    print()
    print(
        "Source:"
    )

    print(
        f"  {SOURCE_HTML}"
    )

    print()
    print(
        "Output:"
    )

    print(
        f"  {OUTPUT_HTML}"
    )

    print()
    print(
        "Local video:"
    )

    print(
        f"  {LOCAL_VIDEO}"
    )

    # --------------------------------------------------------
    # Validate files.
    # --------------------------------------------------------

    if not SOURCE_HTML.exists():

        raise FileNotFoundError(
            f"Source HTML not found:\n"
            f"{SOURCE_HTML}"
        )

    if not LOCAL_VIDEO.exists():

        raise FileNotFoundError(
            f"Local MP4 not found:\n"
            f"{LOCAL_VIDEO}"
        )

    for name, path in {
        "Library":
            LOCAL_LIBRARY,
        "Product":
            LOCAL_PRODUCT,
        "Category":
            LOCAL_CATEGORY,
    }.items():

        if not path.exists():

            raise FileNotFoundError(
                f"{name} page not found:\n"
                f"{path}"
            )

    # --------------------------------------------------------
    # Read source.
    # --------------------------------------------------------

    html = SOURCE_HTML.read_text(
        encoding="utf-8",
        errors="replace",
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # Rewrite links.
    # --------------------------------------------------------

    (
        rewritten_links,
        unmapped_links,
        internal_links,
    ) = rewrite_internal_links(
        soup
    )

    # --------------------------------------------------------
    # Replace video.
    # --------------------------------------------------------

    video_ok, video_message = (
        replace_wistia_player(
            soup,
            LOCAL_VIDEO,
        )
    )

    # --------------------------------------------------------
    # Disable obvious online-only controls.
    # --------------------------------------------------------

    disabled = (
        disable_online_only_elements(
            soup
        )
    )

    # --------------------------------------------------------
    # Add tiny diagnostic marker.
    # --------------------------------------------------------

    marker = Comment(
        " VFXA OFFLINE PROTOTYPE — "
        "original SingleFile capture preserved; "
        "local video/navigation patched "
    )

    if soup.html:

        soup.html.insert(
            0,
            marker,
        )

    # --------------------------------------------------------
    # Write NEW file.
    # --------------------------------------------------------

    OUTPUT_HTML.write_text(
        str(soup),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Summary.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "PROTOTYPE COMPLETE"
    )
    print("=" * 78)

    print()
    print(
        f"Internal VFXA links rewritten : "
        f"{rewritten_links}"
    )

    print(
        f"Internal links still unmapped : "
        f"{unmapped_links}"
    )

    print(
        f"Known internal links examined : "
        f"{internal_links}"
    )

    print(
        f"Online-only controls disabled : "
        f"{disabled}"
    )

    print()
    print(
        f"Video:"
    )

    if video_ok:

        print(
            f"  PASS — {video_message}"
        )

    else:

        print(
            f"  FAIL — {video_message}"
        )

    print()
    print(
        "Generated:"
    )

    print(
        f"  {OUTPUT_HTML}"
    )

    print()
    print(
        "Original browser-extension capture was NOT modified."
    )

    print(
        "MP4/ZIP files were NOT modified."
    )


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\nCancelled."
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}"
        )

        raise