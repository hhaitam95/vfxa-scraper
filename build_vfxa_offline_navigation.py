#!/usr/bin/env python3

"""
VFX Apprentice — Offline Navigation Builder

PURPOSE
-------
Transform the existing captured VFX Apprentice HTML pages into
a locally navigable offline clone.

THIS SCRIPT DOES NOT:
    - download anything
    - contact VFX Apprentice
    - modify MP4 files
    - modify ZIP files
    - modify any non-HTML files

It ONLY modifies existing HTML files.

WHAT IT DOES
------------
1. Reads the authoritative 692-page discovery report.
2. Builds a URL -> local HTML mapping.
3. Understands the repaired Portfolio collision:
       Portfolio - Student Review [POST_ID].html
4. Rewrites VFX Apprentice internal navigation links to
   relative local HTML paths.
5. Preserves URL fragments (#section).
6. Creates .offline-backup copies before modifying HTML.
7. Reports external stylesheet / CSS information.
8. Reports remaining VFX Apprentice links which could not
   be mapped.
9. Produces a verification report.

IMPORTANT
---------
Run this AFTER the successful 692-page capture and collision
repair.

The script can be rerun safely. It always creates/refreshes
the backups before modifying files.
"""


import csv
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import (
    urlparse,
    urlunparse,
    urljoin,
)

from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = Path.cwd()

ARCHIVE_ROOT = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

TREE_REPORT = (
    SCRIPT_DIR
    / "vfxa_library_tree_latest.csv"
)

BACKUP_DIR_NAME = (
    ".offline-backup"
)

LINK_REPORT = (
    SCRIPT_DIR
    / "vfxa_offline_navigation_report.csv"
)

CSS_REPORT = (
    SCRIPT_DIR
    / "vfxa_css_diagnostic.txt"
)


# ============================================================
# HELPERS
# ============================================================

def nfc(value: str) -> str:
    return unicodedata.normalize(
        "NFC",
        str(value),
    )


def sanitize_filename(
    name: str,
) -> str:

    name = str(name).strip()

    name = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        name,
    )

    return name.rstrip(" .") or "_unnamed"


def clean_report_path(
    value: str,
) -> str:

    value = nfc(value.strip())

    # Repair the historical malformed representation.
    value = value.replace(
        r"\.html",
        ".html",
    )

    return value


def load_tree() -> list[dict]:

    if not TREE_REPORT.exists():
        raise FileNotFoundError(
            f"Missing discovery report:\n"
            f"{TREE_REPORT}"
        )

    with TREE_REPORT.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        return list(
            csv.DictReader(f)
        )


def normalize_url(
    url: str,
) -> str:

    """
    Normalize only enough to compare VFXA pages.

    Query strings are discarded because the VFXA page identity
    in our discovery report is based on its page path.
    Fragments are discarded for page matching and restored
    separately when rewriting links.
    """

    if not url:
        return ""

    absolute = urljoin(
        "https://www.vfxapprentice.com",
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

    return urlunparse((
        "https",
        "www.vfxapprentice.com",
        parsed.path.rstrip("/")
            if parsed.path != "/"
            else "/",
        "",
        "",
        "",
    ))


def extract_fragment(
    url: str,
) -> str:

    parsed = urlparse(
        url
    )

    return parsed.fragment


def extract_url_path(
    url: str,
) -> str:

    normalized = normalize_url(
        url
    )

    if not normalized:
        return ""

    return urlparse(
        normalized
    ).path


def post_id_from_url(
    url: str,
) -> str | None:

    match = re.search(
        r"/posts/(\d+)/?$",
        urlparse(url).path,
    )

    if match:
        return match.group(1)

    return None


def relative_path(
    target: Path,
) -> str:

    return nfc(
        str(
            target.relative_to(
                ARCHIVE_ROOT
            )
        )
    )


def safe_target(
    relative: str,
) -> Path:

    target = (
        ARCHIVE_ROOT
        / Path(relative)
    )

    root = (
        ARCHIVE_ROOT.resolve()
    )

    resolved = (
        target.resolve()
    )

    resolved.relative_to(
        root
    )

    return target


# ============================================================
# BUILD AUTHORITATIVE URL -> LOCAL MAP
# ============================================================

def build_url_map(
    rows: list[dict],
):

    discovered = [
        row
        for row in rows
        if row.get(
            "status",
            "",
        ).strip()
        == "DISCOVERED"
    ]

    # Group by original logical local path.
    groups = {}

    for row in discovered:

        local_path = clean_report_path(
            row.get(
                "local_path",
                "",
            )
        )

        if not local_path:
            continue

        key = nfc(
            local_path
        )

        groups.setdefault(
            key,
            [],
        ).append(
            row
        )

    url_to_local = {}

    collision_count = 0

    for local_path, group in groups.items():

        # ----------------------------------------------------
        # Normal unique page.
        # ----------------------------------------------------

        if len(group) == 1:

            row = group[0]

            url = normalize_url(
                row["url"]
            )

            if url:
                url_to_local[
                    url
                ] = Path(
                    local_path
                )

            continue

        # ----------------------------------------------------
        # Collision.
        #
        # Recreate the same naming rule used by the repair:
        #
        #   Title [POST_ID].html
        # ----------------------------------------------------

        collision_count += 1

        for row in group:

            post_id = post_id_from_url(
                row["url"]
            )

            if not post_id:

                raise RuntimeError(
                    "Cannot resolve collision without "
                    f"post ID:\n{row['url']}"
                )

            original = Path(
                local_path
            )

            repaired = (
                original.parent
                / (
                    f"{original.stem} "
                    f"[{post_id}]"
                    f"{original.suffix}"
                )
            )

            url = normalize_url(
                row["url"]
            )

            url_to_local[
                url
            ] = repaired

    return (
        url_to_local,
        collision_count,
        len(discovered),
    )


# ============================================================
# MAP ACTUAL FILES
# ============================================================

def build_actual_html_map():

    result = {}

    for path in ARCHIVE_ROOT.rglob(
        "*.html"
    ):

        # Ignore our backups.
        if (
            BACKUP_DIR_NAME
            in path.parts
        ):
            continue

        key = nfc(
            relative_path(path)
        )

        result[
            key
        ] = path

    return result


# ============================================================
# BACKUP
# ============================================================

def backup_html(
    path: Path,
) -> None:

    backup_root = (
        ARCHIVE_ROOT
        / BACKUP_DIR_NAME
    )

    backup_target = (
        backup_root
        / path.relative_to(
            ARCHIVE_ROOT
        )
    )

    backup_target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        path,
        backup_target,
    )


# ============================================================
# REWRITE ONE HTML FILE
# ============================================================

def rewrite_html(
    html_path: Path,
    url_to_local: dict,
):

    try:

        original = html_path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    except OSError as exc:

        return {
            "status": "READ_FAILED",
            "changed": False,
            "internal_links": 0,
            "rewritten_links": 0,
            "unmapped_vfxa": 0,
            "external_css": 0,
            "inline_css": 0,
            "error": str(exc),
        }

    soup = BeautifulSoup(
        original,
        "html.parser",
    )

    changed = False

    internal_links = 0
    rewritten_links = 0
    unmapped_vfxa = 0

    # --------------------------------------------------------
    # CSS diagnostics.
    # --------------------------------------------------------

    stylesheet_links = soup.find_all(
        "link",
        rel=lambda value:
            value
            and (
                "stylesheet"
                in (
                    value
                    if isinstance(
                        value,
                        list,
                    )
                    else [value]
                )
            ),
    )

    style_tags = soup.find_all(
        "style"
    )

    external_css = 0
    local_css = 0

    for link in stylesheet_links:

        href = link.get(
            "href",
            "",
        )

        if not href:
            continue

        parsed = urlparse(
            urljoin(
                "https://www.vfxapprentice.com",
                href,
            )
        )

        if parsed.scheme in {
            "http",
            "https",
        }:

            external_css += 1

        else:

            local_css += 1

    # --------------------------------------------------------
    # Rewrite anchors.
    # --------------------------------------------------------

    for element in soup.find_all(
        [
            "a",
            "link",
        ],
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

        # ----------------------------------------------------
        # This is an internal VFXA page.
        # ----------------------------------------------------

        internal_links += 1

        target_relative = (
            url_to_local.get(
                normalized
            )
        )

        if target_relative is None:

            # It is VFXA, but wasn't in our 692-page map.
            unmapped_vfxa += 1

            continue

        target_path = safe_target(
            str(
                target_relative
            )
        )

        if not target_path.exists():

            # Don't rewrite to a nonexistent path.
            unmapped_vfxa += 1
            continue

        current_dir = (
            html_path.parent
        )

        local_href = (
            Path(
                target_path
            )
            .relative_to(
                ARCHIVE_ROOT
            )
        )

        # Compute from current HTML's directory.
        absolute_target = (
            ARCHIVE_ROOT
            / local_href
        )

        rel = (
            absolute_target
            .resolve()
            .relative_to(
                ARCHIVE_ROOT.resolve()
            )
        )

        relative_url = (
            __import__(
                "os"
            ).path.relpath(
                absolute_target,
                current_dir,
            )
        )

        fragment = extract_fragment(
            href
        )

        if fragment:
            relative_url += (
                "#"
                + fragment
            )

        if element[
            "href"
        ] != relative_url:

            element[
                "href"
            ] = relative_url

            changed = True
            rewritten_links += 1

    # --------------------------------------------------------
    # Write only if necessary.
    # --------------------------------------------------------

    if changed:

        backup_html(
            html_path
        )

        html_path.write_text(
            str(soup),
            encoding="utf-8",
        )

        status = "REWRITTEN"

    else:

        status = "UNCHANGED"

    return {
        "status":
            status,
        "changed":
            changed,
        "internal_links":
            internal_links,
        "rewritten_links":
            rewritten_links,
        "unmapped_vfxa":
            unmapped_vfxa,
        "external_css":
            external_css,
        "local_css":
            local_css,
        "inline_css":
            len(style_tags),
        "error":
            "",
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE OFFLINE NAVIGATION BUILDER"
    )
    print("=" * 78)

    print()
    print(
        "ARCHIVE:"
    )

    print(
        f"  {ARCHIVE_ROOT}"
    )

    print()
    print(
        "This pass will:"
    )

    print(
        "  - rewrite VFXA navigation links to local files"
    )

    print(
        "  - preserve page fragments"
    )

    print(
        "  - create backups before changing HTML"
    )

    print(
        "  - diagnose CSS availability"
    )

    print()
    print(
        "It will NOT:"
    )

    print(
        "  - download anything"
    )

    print(
        "  - modify MP4 files"
    )

    print(
        "  - modify ZIP files"
    )

    print(
        "  - delete HTML files"
    )

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    if not ARCHIVE_ROOT.exists():

        raise FileNotFoundError(
            f"Archive not found:\n"
            f"{ARCHIVE_ROOT}"
        )

    rows = load_tree()

    (
        url_to_local,
        collision_groups,
        discovered_count,
    ) = build_url_map(
        rows
    )

    actual_html = (
        build_actual_html_map()
    )

    print()
    print(
        f"Discovered VFXA pages: "
        f"{discovered_count}"
    )

    print(
        f"URL -> local mappings: "
        f"{len(url_to_local)}"
    )

    print(
        f"Original collision groups: "
        f"{collision_groups}"
    )

    print(
        f"Actual HTML files: "
        f"{len(actual_html)}"
    )

    if len(url_to_local) != discovered_count:

        print()
        print(
            "WARNING: mapping count does not match discovery count."
        )

    # --------------------------------------------------------
    # Process all actual HTML files.
    # --------------------------------------------------------

    html_files = sorted(
        actual_html.values(),
        key=lambda path:
            str(path).lower(),
    )

    print()
    print(
        f"Processing {len(html_files)} HTML files..."
    )

    report_rows = []

    total_internal = 0
    total_rewritten = 0
    total_unmapped = 0
    total_external_css = 0
    total_inline_css = 0

    rewritten_files = 0
    unchanged_files = 0
    failed_files = 0

    for index, html_path in enumerate(
        html_files,
        start=1,
    ):

        result = rewrite_html(
            html_path,
            url_to_local,
        )

        total_internal += result[
            "internal_links"
        ]

        total_rewritten += result[
            "rewritten_links"
        ]

        total_unmapped += result[
            "unmapped_vfxa"
        ]

        total_external_css += result[
            "external_css"
        ]

        total_inline_css += result[
            "inline_css"
        ]

        if result[
            "status"
        ] == "REWRITTEN":

            rewritten_files += 1

        elif result[
            "status"
        ] == "UNCHANGED":

            unchanged_files += 1

        else:

            failed_files += 1

        report_rows.append({
            "file":
                relative_path(
                    html_path
                ),
            **result,
        })

        if (
            index <= 10
            or index % 50 == 0
            or index == len(html_files)
        ):

            print(
                f"[{index:4d}/"
                f"{len(html_files)}] "
                f"{result['status']:12} "
                f"{html_path.name[:55]}"
            )

    # --------------------------------------------------------
    # Write link report.
    # --------------------------------------------------------

    with LINK_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        fields = [
            "file",
            "status",
            "changed",
            "internal_links",
            "rewritten_links",
            "unmapped_vfxa",
            "external_css",
            "local_css",
            "inline_css",
            "error",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for row in report_rows:

            writer.writerow({
                field:
                    row.get(
                        field,
                        "",
                    )
                for field in fields
            })

    # --------------------------------------------------------
    # CSS diagnostic report.
    # --------------------------------------------------------

    with CSS_REPORT.open(
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "VFX APPRENTICE HTML CSS DIAGNOSTIC\n"
        )

        f.write(
            "=" * 78
            + "\n\n"
        )

        f.write(
            f"HTML files scanned: {len(html_files)}\n"
        )

        f.write(
            f"External stylesheet references: "
            f"{total_external_css}\n"
        )

        f.write(
            f"Inline <style> blocks: "
            f"{total_inline_css}\n"
        )

        f.write(
            f"VFXA internal links found: "
            f"{total_internal}\n"
        )

        f.write(
            f"VFXA links rewritten: "
            f"{total_rewritten}\n"
        )

        f.write(
            f"VFXA links still unmapped: "
            f"{total_unmapped}\n"
        )

        f.write(
            "\n"
        )

        f.write(
            "INTERPRETATION\n"
        )

        f.write(
            "-" * 78
            + "\n"
        )

        if total_external_css == 0:

            f.write(
                "No external stylesheet references were found. "
                "SingleFile appears to have embedded the CSS.\n"
            )

        else:

            f.write(
                "External stylesheet references remain. "
                "This may explain missing styling when offline.\n"
            )

        if total_rewritten == 0:

            f.write(
                "No VFXA links were rewritten. "
                "Navigation may already be local or the "
                "HTML structure needs further inspection.\n"
            )

        else:

            f.write(
                "VFXA internal navigation was converted to "
                "relative local paths.\n"
            )

        if total_unmapped == 0:

            f.write(
                "Every detected internal VFXA page link had "
                "a corresponding discovered local page.\n"
            )

        else:

            f.write(
                "Some VFXA links remain unmapped. "
                "See the CSV report.\n"
            )

    # --------------------------------------------------------
    # Final output.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "OFFLINE NAVIGATION BUILD COMPLETE"
    )
    print("=" * 78)

    print()
    print(
        f"HTML files scanned       : "
        f"{len(html_files)}"
    )

    print(
        f"HTML files rewritten     : "
        f"{rewritten_files}"
    )

    print(
        f"HTML files unchanged     : "
        f"{unchanged_files}"
    )

    print(
        f"HTML files failed        : "
        f"{failed_files}"
    )

    print()
    print(
        f"VFXA links found         : "
        f"{total_internal}"
    )

    print(
        f"VFXA links rewritten     : "
        f"{total_rewritten}"
    )

    print(
        f"VFXA links still unmapped: "
        f"{total_unmapped}"
    )

    print()
    print(
        f"External CSS references  : "
        f"{total_external_css}"
    )

    print(
        f"Inline style blocks      : "
        f"{total_inline_css}"
    )

    print()
    print(
        "Reports:"
    )

    print(
        f"  {LINK_REPORT.resolve()}"
    )

    print(
        f"  {CSS_REPORT.resolve()}"
    )

    print()
    print(
        "HTML backups:"
    )

    print(
        f"  {ARCHIVE_ROOT / BACKUP_DIR_NAME}"
    )

    print()
    print(
        "MP4 and ZIP files were not touched."
    )


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "Cancelled."
        )

        print(
            "No MP4 or ZIP files were modified."
        )

        raise SystemExit(130)

    except Exception as exc:

        print()
        print("=" * 78)
        print(
            "FATAL ERROR"
        )
        print("=" * 78)

        print(
            str(exc)
        )

        raise SystemExit(1)