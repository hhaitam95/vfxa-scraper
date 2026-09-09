#!/usr/bin/env python3

"""
VFX Apprentice — Archive Collision Repair

PURPOSE
-------
Repair filename collisions in the already-downloaded HTML archive.

CURRENT KNOWN COLLISION
-----------------------
10 different lesson URLs were mapped to:

    Apprenticeship Level 3/
    Soft Skills - Explained/
    Portfolio & Application Planning/
    Portfolio - Student Review.html

This script will:

1. Read the existing library discovery report.
2. Find all duplicate local HTML paths.
3. For duplicate POST/lesson paths, extract the VFXA post ID.
4. Create a unique filename for each lesson:

       Portfolio - Student Review [POST_ID].html

5. Download all colliding lessons again using SingleFile.
6. Verify every newly-created file.
7. ONLY after all 10 are successfully verified, remove the old
   shared collision file.

SAFETY
------
This script does NOT touch:

    *.mp4
    *.zip
    *.rar
    *.7z
    *.pdf

It does NOT modify unrelated HTML files.

It does NOT recrawl the entire library.

It only repairs duplicate HTML destinations.

Unicode normalization is handled separately by the audit script.
The apparent "unexpected" VFX creator folders such as:

    Tkác
    Sarı
    Belén

are NOT deleted or renamed here.
"""


import csv
import re
import subprocess
import sys
import time
import unicodedata

from pathlib import Path
from urllib.parse import urlparse


# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = Path.cwd()

TREE_REPORT = (
    SCRIPT_DIR
    / "vfxa_library_tree_latest.csv"
)

COOKIE_FILE = (
    SCRIPT_DIR
    / "cookies.txt"
)

ARCHIVE_ROOT = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

MAX_RETRIES = 3

BROWSER_WIDTH = "1920"
BROWSER_HEIGHT = "1080"
BROWSER_WAIT_UNTIL = "networkIdle"

# Collision pages can be problematic, so give them more time.
BROWSER_WAIT_DELAY = "5000"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# ============================================================
# HELPERS
# ============================================================

def normalize_nfc(value: str) -> str:
    """
    Normalize Unicode for reliable logical comparisons.
    """
    return unicodedata.normalize(
        "NFC",
        str(value),
    )


def load_tree_report():
    if not TREE_REPORT.exists():
        raise FileNotFoundError(
            f"Discovery report not found:\n"
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


def extract_post_id(
    url: str,
) -> str:

    match = re.search(
        r"/posts/(\d+)(?:/)?$",
        urlparse(url).path,
    )

    if not match:
        raise ValueError(
            f"Could not extract post ID from:\n{url}"
        )

    return match.group(1)


def build_unique_collision_filename(
    original_local_path: str,
    post_id: str,
) -> str:

    path = Path(
        original_local_path
    )

    stem = path.stem
    suffix = path.suffix

    return str(
        path.with_name(
            f"{stem} [{post_id}]{suffix}"
        )
    )


def resolve_archive_path(
    relative_path: str,
) -> Path:

    relative = Path(
        relative_path
    )

    if relative.is_absolute():
        raise ValueError(
            f"Absolute path rejected:\n"
            f"{relative_path}"
        )

    target = (
        ARCHIVE_ROOT
        / relative
    )

    archive_resolved = (
        ARCHIVE_ROOT.resolve()
    )

    target_resolved = (
        target.resolve()
    )

    try:
        target_resolved.relative_to(
            archive_resolved
        )
    except ValueError:
        raise ValueError(
            f"Unsafe destination path:\n"
            f"{relative_path}"
        )

    return target


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
            result.stderr.strip()
            or result.stdout.strip()
            or "SingleFile failed."
        )

    print(
        f"SingleFile: {result.stdout.strip()}"
    )


def capture_collision_page(
    row: dict,
    destination: Path,
) -> dict:

    url = row["url"].strip()
    title = row["title"].strip()

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print(
        "-" * 78
    )

    print(
        f"TITLE : {title}"
    )

    print(
        f"URL   : {url}"
    )

    print(
        f"POST ID: {extract_post_id(url)}"
    )

    print(
        f"OUTPUT: {destination}"
    )

    last_error = ""

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        print()
        print(
            f"Attempt {attempt}/{MAX_RETRIES}"
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

            url,

            # Complete absolute destination.
            str(destination),
        ]

        started = time.monotonic()

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
            )

        except Exception as exc:

            elapsed = (
                time.monotonic()
                - started
            )

            last_error = str(exc)

            print(
                f"Process exception "
                f"after {elapsed:.1f}s:"
            )

            print(
                last_error
            )

            if attempt < MAX_RETRIES:
                time.sleep(2)

            continue

        elapsed = (
            time.monotonic()
            - started
        )

        print(
            f"SingleFile exit code: "
            f"{result.returncode}"
        )

        print(
            f"Elapsed: "
            f"{elapsed:.1f}s"
        )

        if result.returncode != 0:

            last_error = (
                result.stderr.strip()
                or result.stdout.strip()
                or "Unknown SingleFile error."
            )

            print(
                last_error[:1000]
            )

            if attempt < MAX_RETRIES:
                print(
                    "Retrying..."
                )
                time.sleep(2)

            continue

        # ----------------------------------------------------
        # Verify actual filesystem result.
        # ----------------------------------------------------

        if not destination.exists():

            last_error = (
                "SingleFile returned success, "
                "but the output file was not created."
            )

            print(
                last_error
            )

            if attempt < MAX_RETRIES:
                print(
                    "Retrying..."
                )
                time.sleep(2)

            continue

        size = destination.stat().st_size

        if size == 0:

            last_error = (
                "Output file exists but is zero bytes."
            )

            print(
                last_error
            )

            if attempt < MAX_RETRIES:
                print(
                    "Retrying..."
                )
                time.sleep(2)

            continue

        print()
        print(
            f"SUCCESS: "
            f"{size:,} bytes "
            f"({size / 1024 / 1024:.2f} MB)"
        )

        return {
            "success": True,
            "size": size,
            "error": "",
            "attempts": attempt,
        }

    return {
        "success": False,
        "size": (
            destination.stat().st_size
            if destination.exists()
            else 0
        ),
        "error": last_error,
        "attempts": MAX_RETRIES,
    }


# ============================================================
# FIND COLLISIONS
# ============================================================

def find_collisions(
    rows,
):

    groups = {}

    for row in rows:

        if row.get(
            "status",
            "",
        ).strip() != "DISCOVERED":
            continue

        local_path = normalize_nfc(
            row.get(
                "local_path",
                "",
            ).strip()
        )

        if not local_path:
            continue

        groups.setdefault(
            local_path,
            [],
        ).append(row)

    collisions = {
        path: items
        for path, items in groups.items()
        if len(items) > 1
    }

    return collisions


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE HTML COLLISION REPAIR"
    )
    print("=" * 78)

    print()
    print(
        f"Archive:"
    )

    print(
        f"  {ARCHIVE_ROOT}"
    )

    print()
    print(
        "This script will ONLY repair duplicate HTML paths."
    )

    print(
        "MP4 and ZIP files will NOT be touched."
    )

    print()

    if not ARCHIVE_ROOT.exists():
        raise FileNotFoundError(
            f"Archive not found:\n"
            f"{ARCHIVE_ROOT}"
        )

    if not COOKIE_FILE.exists():
        raise FileNotFoundError(
            f"Cookie file not found:\n"
            f"{COOKIE_FILE}"
        )

    verify_singlefile()

    rows = load_tree_report()

    collisions = find_collisions(
        rows
    )

    print()
    print(
        f"Collision groups found: "
        f"{len(collisions)}"
    )

    if not collisions:

        print()
        print(
            "No duplicate local paths found."
        )

        return

    # --------------------------------------------------------
    # Display collisions.
    # --------------------------------------------------------

    for local_path, items in collisions.items():

        print()
        print("=" * 78)

        print(
            f"COLLISION: {local_path}"
        )

        print(
            f"Occurrences: {len(items)}"
        )

        print("=" * 78)

        for row in items:

            print()
            print(
                f"  {row['title']}"
            )

            print(
                f"  {row['url']}"
            )

    # --------------------------------------------------------
    # We expect the known Portfolio collision.
    #
    # This script is conservative: only POST collisions are
    # repaired, because those can safely be made unique using
    # their post IDs.
    # --------------------------------------------------------

    repair_jobs = []

    for local_path, items in collisions.items():

        for row in items:

            if (
                row.get("type", "")
                .strip()
                != "post"
            ):

                raise RuntimeError(
                    "Found a non-post collision. "
                    "Stopping rather than guessing how to "
                    f"repair:\n{local_path}"
                )

            post_id = extract_post_id(
                row["url"]
            )

            unique_relative = (
                build_unique_collision_filename(
                    local_path,
                    post_id,
                )
            )

            destination = resolve_archive_path(
                unique_relative
            )

            repair_jobs.append({
                "row":
                    row,
                "original_local_path":
                    local_path,
                "unique_relative":
                    unique_relative,
                "destination":
                    destination,
            })

    # --------------------------------------------------------
    # Safety confirmation.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "REPAIR PLAN"
    )
    print("=" * 78)

    for job in repair_jobs:

        print()
        print(
            f"  {job['row']['title']}"
        )

        print(
            f"    URL:"
        )

        print(
            f"      {job['row']['url']}"
        )

        print(
            f"    NEW:"
        )

        print(
            f"      {job['destination']}"
        )

    print()
    print(
        "The old shared collision file will NOT be deleted "
        "until every new file succeeds."
    )

    print()

    confirmation = input(
        "Type REPAIR to continue: "
    ).strip()

    if confirmation != "REPAIR":

        print()
        print(
            "Cancelled. Nothing was changed."
        )

        return

    # --------------------------------------------------------
    # Download all unique copies.
    # --------------------------------------------------------

    results = []

    for index, job in enumerate(
        repair_jobs,
        start=1,
    ):

        print()
        print(
            f"[{index}/{len(repair_jobs)}]"
        )

        result = capture_collision_page(
            job["row"],
            job["destination"],
        )

        results.append({
            **job,
            **result,
        })

    # --------------------------------------------------------
    # Validate every repair.
    # --------------------------------------------------------

    failed = [
        result
        for result in results
        if not result["success"]
    ]

    print()
    print("=" * 78)
    print(
        "REPAIR VERIFICATION"
    )
    print("=" * 78)

    for result in results:

        status = (
            "PASS"
            if result["success"]
            else "FAIL"
        )

        print()
        print(
            f"{status}: "
            f"{result['unique_relative']}"
        )

        if not result["success"]:

            print(
                f"  {result['error']}"
            )

    # --------------------------------------------------------
    # NEVER remove the old collision file if anything failed.
    # --------------------------------------------------------

    if failed:

        print()
        print(
            "=" * 78
        )

        print(
            "REPAIR INCOMPLETE"
        )

        print(
            "=" * 78
        )

        print()
        print(
            f"{len(failed)} page(s) failed."
        )

        print(
            "The original collision file was NOT deleted."
        )

        print(
            "This preserves the previously captured content."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # All 10 unique pages now exist.
    #
    # Only now remove the old shared filename.
    # This is the ONLY deletion performed by this script.
    # --------------------------------------------------------

    original_paths = {
        result["original_local_path"]
        for result in results
    }

    for original_relative in original_paths:

        original_path = resolve_archive_path(
            original_relative
        )

        print()
        print(
            f"Removing old collision file:"
        )

        print(
            f"  {original_path}"
        )

        if not original_path.exists():

            print(
                "  Already absent."
            )

            continue

        if original_path.suffix.lower() != ".html":

            raise RuntimeError(
                "Safety check failed: "
                "collision target is not .html."
            )

        original_path.unlink()

        print(
            "  Removed."
        )

    # --------------------------------------------------------
    # Final validation.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "COLLISION REPAIR COMPLETE"
    )
    print("=" * 78)

    print()
    print(
        f"Collision groups repaired: "
        f"{len(collisions)}"
    )

    print(
        f"Pages repaired: "
        f"{len(results)}"
    )

    print(
        f"Unique HTML files created: "
        f"{len(results)}"
    )

    print()
    print(
        "All repaired filenames now contain their VFXA post ID."
    )

    print(
        "MP4 and ZIP files were not touched."
    )

    print()
    print(
        "Next: rerun the archive audit."
    )


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print()
        print(
            "Cancelled by user."
        )

        sys.exit(130)

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

        sys.exit(1)