#!/usr/bin/env python3

"""
VFX Apprentice — Offline Lesson Prototype v2

TEST ONLY
---------

Creates a clean offline page for:

    Composition (Staging)

from:

    Composition (Staging).html

IMPORTANT
---------
The original SingleFile HTML is NEVER modified.

The generated page is:

    Composition (Staging).offline.html

This version uses the LOCAL HTML filename as the lesson
identity instead of relying on the site's global <title>,
which was found to be:

    VFX Apprentice | Training FX Artists for Games and Animation

It also explicitly searches for:

    Composition (Staging).mp4

in the same directory.
"""


from pathlib import Path
from html import escape
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

ARCHIVE_ROOT = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

LESSON_DIR = (
    ARCHIVE_ROOT
    / "Hand-Drawn 2D FX_ Level 1"
    / "FX Design Principles - Explained"
)

SOURCE_HTML = (
    LESSON_DIR
    / "Composition (Staging).html"
)

OUTPUT_HTML = (
    LESSON_DIR
    / "Composition (Staging).offline.html"
)


# ============================================================
# LESSON IDENTITY
# ============================================================

def get_lesson_title(
    source_html: Path,
) -> str:
    """
    The local filename is authoritative.

    Composition (Staging).html
    ->
    Composition (Staging)
    """

    return source_html.stem


# ============================================================
# VIDEO
# ============================================================

def find_local_video(
    lesson_dir: Path,
    lesson_title: str,
):
    """
    Look for the exact filename matching the lesson title.
    """

    expected = (
        lesson_dir
        / f"{lesson_title}.mp4"
    )

    if expected.exists():

        return expected

    # Conservative fallback:
    # case-insensitive exact stem comparison.
    normalized_target = (
        lesson_title
        .casefold()
        .strip()
    )

    for path in lesson_dir.glob(
        "*.mp4"
    ):

        if (
            path.stem
            .casefold()
            .strip()
            == normalized_target
        ):

            return path

    return None


# ============================================================
# EXTRACT CONTENT
# ============================================================

def extract_content(
    source_html: Path,
):
    """
    Extract the useful visible lesson content from the
    SingleFile document.

    We deliberately avoid using the document <title>.
    """

    html = source_html.read_text(
        encoding="utf-8",
        errors="replace",
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # Find likely lesson body.
    #
    # Prefer containers that are commonly used for Kajabi /
    # lesson content, then fall back to article/main/body.
    # --------------------------------------------------------

    selectors = [
        ".post-content",
        ".post-body",
        ".course-post-content",
        ".lesson-content",
        ".content-body",
        "article",
        "main",
        "body",
    ]

    body = None

    for selector in selectors:

        candidate = soup.select_one(
            selector
        )

        if candidate is not None:

            # Avoid selecting an enormous generic wrapper
            # when a more specific candidate exists.
            body = candidate
            break

    if body is None:

        return (
            "",
            soup,
        )

    # --------------------------------------------------------
    # Remove site chrome / scripts / player containers.
    # --------------------------------------------------------

    remove_selectors = [
        "script",
        "noscript",
        "iframe",
        "nav",
        "header",
        "footer",
        ".breadcrumbs",
        ".navigation",
        ".comments",
        ".comment",
        ".downloads",
        ".download",
        ".video",
        ".wistia_embed",
        ".wistia_responsive_padding",
        ".wistia_responsive_wrapper",
    ]

    for selector in remove_selectors:

        for element in body.select(
            selector
        ):

            element.decompose()

    # --------------------------------------------------------
    # Remove obvious VFXA application chrome.
    # --------------------------------------------------------

    for element in body.find_all(
        class_=True
    ):

        classes = " ".join(
            element.get("class", [])
        ).lower()

        if any(
            token in classes
            for token in (
                "sidebar",
                "course-nav",
                "topbar",
                "navbar",
                "user-menu",
                "footer",
                "header",
            )
        ):

            element.decompose()

    return (
        str(body),
        soup,
    )


# ============================================================
# RESOURCES
# ============================================================

def find_local_resources(
    lesson_dir: Path,
):
    """
    Existing local non-video downloadable resources.
    """

    resources = []

    for path in sorted(
        lesson_dir.iterdir(),
        key=lambda p:
            p.name.casefold(),
    ):

        if not path.is_file():
            continue

        if path.suffix.lower() in {
            ".zip",
            ".rar",
            ".7z",
            ".pdf",
        }:

            resources.append(path)

    return resources


# ============================================================
# RELATIVE LINKS
# ============================================================

def relative_href(
    current_file: Path,
    target_file: Path,
) -> str:

    return str(
        target_file.relative_to(
            current_file.parent
        )
    )


# ============================================================
# BUILD PAGE
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE OFFLINE LESSON PROTOTYPE v2"
    )
    print("=" * 78)

    print()

    if not SOURCE_HTML.exists():

        raise FileNotFoundError(
            f"Source HTML not found:\n"
            f"{SOURCE_HTML}"
        )

    lesson_title = get_lesson_title(
        SOURCE_HTML
    )

    print(
        f"Lesson: {lesson_title}"
    )

    print(
        f"Source: {SOURCE_HTML}"
    )

    # --------------------------------------------------------
    # Extract lesson body.
    # --------------------------------------------------------

    body_html, original_soup = (
        extract_content(
            SOURCE_HTML
        )
    )

    if not body_html:

        body_html = (
            "<p>"
            "No lesson content could be extracted."
            "</p>"
        )

    # --------------------------------------------------------
    # Find local video.
    # --------------------------------------------------------

    video = find_local_video(
        LESSON_DIR,
        lesson_title,
    )

    if video:

        print()
        print(
            f"VIDEO FOUND:"
        )

        print(
            f"  {video}"
        )

        video_href = relative_href(
            OUTPUT_HTML,
            video,
        )

    else:

        print()
        print(
            "VIDEO NOT FOUND:"
        )

        print(
            f"  Expected: "
            f"{LESSON_DIR / (lesson_title + '.mp4')}"
        )

        video_href = None

    # --------------------------------------------------------
    # Local resources.
    # --------------------------------------------------------

    resources = find_local_resources(
        LESSON_DIR
    )

    print()
    print(
        f"Local resources found: "
        f"{len(resources)}"
    )

    # --------------------------------------------------------
    # Build video section.
    # --------------------------------------------------------

    if video_href:

        video_section = f"""
        <section class="media-section">

            <h2>Lesson Video</h2>

            <video
                class="lesson-video"
                controls
                preload="metadata"
            >
                <source
                    src="{escape(video_href)}"
                    type="video/mp4"
                >

                Your browser does not support
                HTML5 video.
            </video>

        </section>
        """

    else:

        video_section = """
        <section class="media-section">

            <h2>Lesson Video</h2>

            <div class="missing">
                No matching local MP4 was found.
            </div>

        </section>
        """

    # --------------------------------------------------------
    # Resources.
    # --------------------------------------------------------

    if resources:

        resources_html = """
        <section class="resources">

            <h2>Resources</h2>

            <div class="resource-list">
        """

        for resource in resources:

            href = relative_href(
                OUTPUT_HTML,
                resource,
            )

            resources_html += f"""
                <a
                    class="resource"
                    href="{escape(href)}"
                    download
                >
                    {escape(resource.name)}
                </a>
            """

        resources_html += """
            </div>
        </section>
        """

    else:

        resources_html = ""

    # --------------------------------------------------------
    # Breadcrumbs.
    # --------------------------------------------------------

    breadcrumbs = """
        <div class="breadcrumbs">

            <a href="../../../index.html">
                Library
            </a>

            <span>›</span>

            <a href="../../index.html">
                Hand-Drawn 2D FX: Level 1
            </a>

            <span>›</span>

            <a href="../index.html">
                FX Design Principles - Explained
            </a>

            <span>›</span>

            <span>
                Composition (Staging)
            </span>

        </div>
    """

    # --------------------------------------------------------
    # Final standalone page.
    # --------------------------------------------------------

    page = f"""<!doctype html>

<html lang="en">

<head>

    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>
        {escape(lesson_title)}
        — VFX Apprentice Offline
    </title>

    <style>

        :root {{
            color-scheme: dark;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;

            background: #111;
            color: #eee;

            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;

            line-height: 1.6;
        }}

        .page {{
            width: min(
                1200px,
                calc(100% - 48px)
            );

            margin: 0 auto;

            padding:
                36px
                0
                80px;
        }}

        .breadcrumbs {{
            display: flex;
            flex-wrap: wrap;

            gap: 8px;

            margin-bottom: 28px;

            font-size: 14px;

            color: #999;
        }}

        .breadcrumbs a {{
            color: #bbb;
            text-decoration: none;
        }}

        .breadcrumbs a:hover {{
            text-decoration: underline;
        }}

        h1 {{
            font-size: 40px;
            line-height: 1.2;

            margin:
                0
                0
                36px;
        }}

        h2 {{
            margin:
                42px
                0
                18px;

            font-size: 24px;
        }}

        .lesson-body {{
            padding: 28px;

            background: #1a1a1a;

            border:
                1px solid
                #333;

            border-radius: 12px;

            overflow: hidden;
        }}

        .lesson-body img {{
            max-width: 100%;
            height: auto;
        }}

        .lesson-body video {{
            max-width: 100%;
        }}

        .lesson-body a {{
            color: #8dc6ff;
        }}

        .lesson-body table {{
            max-width: 100%;
            overflow-x: auto;
        }}

        .media-section {{
            margin-top: 30px;
        }}

        .lesson-video {{
            display: block;

            width: 100%;

            max-height: 720px;

            background: #000;

            border-radius: 12px;
        }}

        .resources {{
            margin-top: 36px;
        }}

        .resource-list {{
            display: flex;
            flex-direction: column;

            gap: 10px;
        }}

        .resource {{
            display: block;

            padding: 14px 18px;

            color: #ddd;

            text-decoration: none;

            background: #1a1a1a;

            border:
                1px solid
                #333;

            border-radius: 8px;
        }}

        .resource:hover {{
            background: #242424;
        }}

        .missing {{
            padding: 18px;

            background: #241818;

            border:
                1px solid
                #553333;

            border-radius: 8px;
        }}

        .source-note {{
            margin-top: 50px;

            padding-top: 20px;

            border-top:
                1px solid
                #333;

            color: #777;

            font-size: 13px;
        }}

    </style>

</head>

<body>

    <main class="page">

        {breadcrumbs}

        <h1>
            {escape(lesson_title)}
        </h1>

        {video_section}

        <section>

            <h2>Lesson Content</h2>

            <div class="lesson-body">

                {body_html}

            </div>

        </section>

        {resources_html}

        <div class="source-note">
            VFX Apprentice offline archive.
        </div>

    </main>

</body>

</html>
"""

    OUTPUT_HTML.write_text(
        page,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Summary.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "PROTOTYPE CREATED"
    )
    print("=" * 78)

    print()
    print(
        f"Output:"
    )

    print(
        f"  {OUTPUT_HTML}"
    )

    print()
    print(
        "The original SingleFile HTML was not modified."
    )

    print(
        "No MP4/ZIP files were modified."
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