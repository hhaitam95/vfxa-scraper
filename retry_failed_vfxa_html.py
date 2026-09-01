#!/usr/bin/env python3

"""
VFX Apprentice — Targeted HTML Failure Recovery

PURPOSE
-------
Retry ONLY the HTML pages that were recorded as:

    FAILED_OUTPUT_MISSING

in:

    vfxa_html_download_report_latest.csv

This script does NOT:
    - crawl the library again
    - modify successful HTML pages
    - download MP4 files
    - download ZIP files
    - delete files
    - touch any non-HTML resources

The exact local_path recorded in the original report is used,
so this retry does not perform any new path mapping.

RETRY STRATEGY
--------------
Each failed page is attempted up to MAX_RETRIES times.

The retry uses:
    networkIdle
    5000 ms additional wait

This is intentionally slower than the main run because these
15 pages have already demonstrated that they are problematic.

REQUIREMENTS
------------
- Python 3
- SingleFile CLI 2.0.83
- requests
- beautifulsoup4
- cookies.txt
- vfxa_html_download_report_latest.csv
"""


import csv
import subprocess
import sys
import time
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path.cwd()

REPORT_FILE = (
    BASE_DIR
    / "vfxa_html_download_report_latest.csv"
)

COOKIE_FILE = (
    BASE_DIR
    / "cookies.txt"
)

ARCHIVE_ROOT = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "VFX Apprentice Downloads"
)

OUTPUT_REPORT = (
    BASE_DIR
    / "vfxa_failed_html_retry_report.csv"
)

# ------------------------------------------------------------
# Retry behavior
# ------------------------------------------------------------

MAX_RETRIES = 3

RETRY_DELAY_SECONDS = 2.0

# Give problematic pages substantially more time than the
# normal 1000 ms used in the full crawl.
BROWSER_WAIT_UNTIL = "networkIdle"
BROWSER_WAIT_DELAY = "5000"

BROWSER_WIDTH = "1920"
BROWSER_HEIGHT = "1080"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


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

    version = result.stdout.strip()

    print(
        f"SingleFile: {version}"
    )


# ============================================================
# LOAD FAILURE LIST
# ============================================================

def load_failed_pages():
    if not REPORT_FILE.exists():
        raise FileNotFoundError(
            f"Report not found:\n"
            f"{REPORT_FILE}"
        )

    failed = []

    with REPORT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        reader = csv.DictReader(f)

        required = {
            "type",
            "title",
            "url",
            "local_path",
            "status",
        }

        missing_columns = (
            required
            - set(reader.fieldnames or [])
        )

        if missing_columns:
            raise RuntimeError(
                "The report is missing required columns: "
                + ", ".join(
                    sorted(missing_columns)
                )
            )

        for row in reader:

            if (
                row.get("status", "").strip()
                == "FAILED_OUTPUT_MISSING"
            ):

                failed.append(row)

    return failed


# ============================================================
# TARGET PATH
# ============================================================

def resolve_target_path(
    local_path: str,
) -> Path:
    """
    The original report stores paths relative to the archive.

    Example:
        Hand-Drawn 2D FX_ Level 1/Foo/Bar.html

    We resolve that against the CURRENT archive root.

    Absolute paths are rejected because the report should contain
    relative paths and we want a strict safety boundary.
    """

    relative = Path(
        local_path.strip()
    )

    if not local_path.strip():
        raise ValueError(
            "Empty local_path in report."
        )

    if relative.is_absolute():
        raise ValueError(
            f"Refusing absolute local_path from report: "
            f"{local_path}"
        )

    target = (
        ARCHIVE_ROOT
        / relative
    )

    # Safety check: ensure target remains inside archive root.
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
    except ValueError as exc:
        raise ValueError(
            f"Unsafe target path:\n"
            f"{local_path}"
        ) from exc

    return target


# ============================================================
# RETRY ONE PAGE
# ============================================================

def retry_one_page(
    row: dict,
):
    title = row["title"].strip()
    url = row["url"].strip()
    local_path = row["local_path"].strip()

    target = resolve_target_path(
        local_path
    )

    print()
    print("=" * 78)
    print(
        f"TARGET: {title}"
    )
    print(
        f"URL   : {url}"
    )
    print(
        f"PATH  : {target}"
    )
    print("=" * 78)

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # MP4/ZIP files are never touched. We only operate on this
    # exact .html destination.
    # --------------------------------------------------------

    if target.suffix.lower() != ".html":
        return {
            **row,
            "retry_status":
                "REFUSED_NON_HTML_TARGET",
            "attempts": 0,
            "final_size_bytes": 0,
            "error":
                "Target is not .html",
        }

    previous_size = 0

    if target.exists():
        previous_size = target.stat().st_size

        print(
            f"Existing HTML size: "
            f"{previous_size:,} bytes"
        )

        print(
            "It will be replaced if SingleFile succeeds."
        )

    last_error = ""

    # --------------------------------------------------------
    # Retry loop
    # --------------------------------------------------------

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

            # Explicitly overwrite the exact target.
            "--filename-conflict-action",
            "overwrite",

            # URL
            url,

            # COMPLETE ABSOLUTE OUTPUT PATH.
            str(target),
        ]

        print(
            "Launching SingleFile..."
        )

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
                f"Process exception after "
                f"{elapsed:.1f}s:"
            )

            print(
                f"  {last_error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(
                    RETRY_DELAY_SECONDS
                )

            continue

        elapsed = (
            time.monotonic()
            - started
        )

        print(
            f"SingleFile exited with code "
            f"{result.returncode} "
            f"after {elapsed:.1f}s"
        )

        if result.returncode != 0:

            last_error = (
                result.stderr.strip()
                or result.stdout.strip()
                or "Unknown SingleFile error"
            )

            print(
                "SingleFile error:"
            )

            print(
                last_error[:1000]
            )

            if attempt < MAX_RETRIES:
                print(
                    f"Retrying in "
                    f"{RETRY_DELAY_SECONDS:.1f}s..."
                )

                time.sleep(
                    RETRY_DELAY_SECONDS
                )

            continue

        # ----------------------------------------------------
        # Verify actual output.
        # ----------------------------------------------------

        if not target.exists():

            last_error = (
                "SingleFile exited successfully, "
                "but expected output file does not exist."
            )

            print(
                last_error
            )

            if attempt < MAX_RETRIES:

                print(
                    f"Retrying in "
                    f"{RETRY_DELAY_SECONDS:.1f}s..."
                )

                time.sleep(
                    RETRY_DELAY_SECONDS
                )

            continue

        size = target.stat().st_size

        if size == 0:

            last_error = (
                "SingleFile created an empty file."
            )

            print(
                last_error
            )

            if attempt < MAX_RETRIES:

                print(
                    f"Retrying in "
                    f"{RETRY_DELAY_SECONDS:.1f}s..."
                )

                time.sleep(
                    RETRY_DELAY_SECONDS
                )

            continue

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        print()
        print(
            f"SUCCESS — "
            f"{size:,} bytes "
            f"({size / 1024 / 1024:.2f} MB)"
        )

        return {
            **row,
            "retry_status":
                "RECOVERED",
            "attempts":
                attempt,
            "final_size_bytes":
                size,
            "error":
                "",
        }

    # --------------------------------------------------------
    # Failed all attempts
    # --------------------------------------------------------

    print()
    print(
        f"FAILED after {MAX_RETRIES} attempts."
    )

    return {
        **row,
        "retry_status":
            "FAILED_AFTER_RETRIES",
        "attempts":
            MAX_RETRIES,
        "final_size_bytes":
            (
                target.stat().st_size
                if target.exists()
                else 0
            ),
        "error":
            last_error,
    }


# ============================================================
# REPORT
# ============================================================

def write_report(
    results,
):
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
        "retry_status",
        "attempts",
        "final_size_bytes",
    ]

    with OUTPUT_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for row in results:

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
        "VFX APPRENTICE FAILED HTML RECOVERY"
    )
    print("=" * 78)

    print()
    print(
        f"Report:"
    )

    print(
        f"  {REPORT_FILE}"
    )

    print()
    print(
        f"Archive:"
    )

    print(
        f"  {ARCHIVE_ROOT}"
    )

    print()
    print(
        "Retry policy:"
    )

    print(
        f"  Maximum attempts : {MAX_RETRIES}"
    )

    print(
        f"  Wait-until       : "
        f"{BROWSER_WAIT_UNTIL}"
    )

    print(
        f"  Additional wait   : "
        f"{BROWSER_WAIT_DELAY} ms"
    )

    print()
    print(
        "SAFETY:"
    )

    print(
        "  Only FAILED_OUTPUT_MISSING rows are retried."
    )

    print(
        "  Only .html targets are allowed."
    )

    print(
        "  MP4 files are NOT touched."
    )

    print(
        "  ZIP files are NOT touched."
    )

    print(
        "  No files are deleted."
    )

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    if not COOKIE_FILE.exists():
        raise FileNotFoundError(
            f"Cookie file not found:\n"
            f"{COOKIE_FILE}"
        )

    if not ARCHIVE_ROOT.exists():
        raise FileNotFoundError(
            f"Archive root not found:\n"
            f"{ARCHIVE_ROOT}"
        )

    verify_singlefile()

    failed_pages = load_failed_pages()

    print()
    print(
        f"FAILED_OUTPUT_MISSING pages found: "
        f"{len(failed_pages)}"
    )

    if not failed_pages:

        print()
        print(
            "Nothing to retry."
        )

        return

    # --------------------------------------------------------
    # Display exact targets first.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "RECOVERY TARGETS"
    )
    print("=" * 78)

    for index, row in enumerate(
        failed_pages,
        start=1,
    ):

        target = resolve_target_path(
            row["local_path"]
        )

        print()
        print(
            f"{index:02d}. {row['title']}"
        )

        print(
            f"    URL : {row['url']}"
        )

        print(
            f"    PATH: {target}"
        )

    # --------------------------------------------------------
    # Run retries.
    # --------------------------------------------------------

    results = []

    started_all = time.monotonic()

    for index, row in enumerate(
        failed_pages,
        start=1,
    ):

        print()
        print(
            f"[{index}/{len(failed_pages)}]"
        )

        result = retry_one_page(
            row
        )

        results.append(
            result
        )

    elapsed_all = (
        time.monotonic()
        - started_all
    )

    write_report(
        results
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    recovered = sum(
        1
        for row in results
        if row["retry_status"]
        == "RECOVERED"
    )

    failed = sum(
        1
        for row in results
        if row["retry_status"]
        == "FAILED_AFTER_RETRIES"
    )

    refused = sum(
        1
        for row in results
        if row["retry_status"]
        == "REFUSED_NON_HTML_TARGET"
    )

    print()
    print("=" * 78)
    print(
        "RECOVERY COMPLETE"
    )
    print("=" * 78)

    print()
    print(
        f"Original failed pages : "
        f"{len(failed_pages)}"
    )

    print(
        f"Recovered             : "
        f"{recovered}"
    )

    print(
        f"Still failed          : "
        f"{failed}"
    )

    print(
        f"Refused by safety     : "
        f"{refused}"
    )

    print(
        f"Total elapsed         : "
        f"{elapsed_all / 60:.1f} minutes"
    )

    print()
    print(
        "Retry report:"
    )

    print(
        f"  {OUTPUT_REPORT.resolve()}"
    )

    print()
    print(
        "MP4 and ZIP files were not touched."
    )

    if failed:

        print()
        print(
            "Pages still failing:"
        )

        for row in results:

            if (
                row["retry_status"]
                == "FAILED_AFTER_RETRIES"
            ):

                print(
                    f"  - {row['title']}"
                )

                print(
                    f"    {row['url']}"
                )

    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "Recovery cancelled by user."
        )

        print(
            "No MP4 or ZIP files were modified."
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