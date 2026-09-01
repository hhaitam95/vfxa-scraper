#!/usr/bin/env python3

"""
VFX Apprentice — FINAL Archive Integrity Audit

READ-ONLY
---------

This audit understands the archive's filename-collision repair.

It does NOT modify, delete, move, or rename anything.

It verifies:

    - 692 discovered VFXA pages
    - collision-repaired lesson filenames
    - Unicode-normalized macOS filenames
    - missing HTML
    - zero-byte HTML
    - truly unexpected HTML
    - leftover .htm
    - duplicate logical destinations
    - MP4 count/size
    - ZIP count/size

SPECIAL COLLISION RULE
----------------------

When multiple VFXA POST URLs originally mapped to the same
local HTML path, the repaired archive uses:

    Original Title [POST_ID].html

Example:

    Portfolio - Student Review [2183004837].html

This audit derives those expected filenames automatically from
the VFXA post IDs in the discovery report.

UNICODE
-------

macOS may store accented filenames in decomposed Unicode form.

The audit therefore compares logical paths using NFC normalization
so that:

    Tkáč

and:

    Tkác + combining acute

are treated as the same filename.
"""


import csv
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse
import re


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

HTML_REPORT = (
    SCRIPT_DIR
    / "vfxa_html_download_report_latest.csv"
)

MP4_INVENTORY = (
    SCRIPT_DIR
    / "vfx_apprentice_mp4_inventory.csv"
)

AUDIT_REPORT = (
    SCRIPT_DIR
    / "vfxa_archive_final_audit.csv"
)

SUMMARY_REPORT = (
    SCRIPT_DIR
    / "vfxa_archive_final_summary.txt"
)


# ============================================================
# HELPERS
# ============================================================

def nfc(value: str) -> str:
    """
    Normalize text to Unicode NFC and strip whitespace.
    """
    return unicodedata.normalize(
        "NFC",
        str(value).strip(),
    )


def clean_report_path(
    value: str,
) -> str:
    """
    Clean a local path stored in the CSV.

    The old discovery process produced one collision filename
    containing an escaped dot:

        Portfolio - Student Review\.html

    Treat that as the ordinary filename:

        Portfolio - Student Review.html
    """

    value = nfc(value)

    # Only remove the specific erroneous escaped dot.
    value = value.replace(
        r"\.html",
        ".html",
    )

    return value


def load_csv(
    path: Path,
) -> list[dict]:

    if not path.exists():
        raise FileNotFoundError(
            f"Required report not found:\n{path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        return list(
            csv.DictReader(f)
        )


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


def human_size(
    value: int,
) -> str:

    size = float(value)

    for unit in (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    ):

        if size < 1024:
            return f"{size:.2f} {unit}"

        size /= 1024

    return f"{size:.2f} PB"


def actual_relative(
    path: Path,
) -> str:

    return nfc(
        str(
            path.relative_to(
                ARCHIVE_ROOT
            )
        )
    )


def safe_archive_path(
    relative_path: str,
) -> Path:

    relative = Path(
        relative_path
    )

    if relative.is_absolute():
        raise ValueError(
            f"Absolute archive path rejected: "
            f"{relative_path}"
        )

    target = (
        ARCHIVE_ROOT
        / relative
    )

    root_resolved = (
        ARCHIVE_ROOT.resolve()
    )

    target_resolved = (
        target.resolve()
    )

    try:
        target_resolved.relative_to(
            root_resolved
        )
    except ValueError as exc:
        raise ValueError(
            f"Unsafe archive path: "
            f"{relative_path}"
        ) from exc

    return target


# ============================================================
# BUILD EXPECTED PAGE SET
# ============================================================

def build_expected_pages(
    tree_rows: list[dict],
) -> tuple[
    dict[str, dict],
    dict[str, list[dict]],
]:

    discovered = []

    for row in tree_rows:

        if (
            row.get(
                "status",
                "",
            ).strip()
            != "DISCOVERED"
        ):
            continue

        raw_path = row.get(
            "local_path",
            "",
        ).strip()

        if not raw_path:
            continue

        local_path = clean_report_path(
            raw_path
        )

        row_copy = dict(row)

        row_copy[
            "local_path_clean"
        ] = local_path

        discovered.append(
            row_copy
        )

    # --------------------------------------------------------
    # Group by normalized logical path.
    # --------------------------------------------------------

    groups = defaultdict(list)

    for row in discovered:

        groups[
            nfc(
                row[
                    "local_path_clean"
                ]
            )
        ].append(
            row
        )

    expected = {}
    collision_groups = {}

    # --------------------------------------------------------
    # Build final expected paths.
    # --------------------------------------------------------

    for logical_path, rows in groups.items():

        if len(rows) == 1:

            row = rows[0]

            expected[
                logical_path
            ] = {
                "type":
                    row.get("type", ""),
                "title":
                    row.get("title", ""),
                "url":
                    row.get("url", ""),
                "parent_url":
                    row.get("parent_url", ""),
                "original_local_path":
                    row[
                        "local_path_clean"
                    ],
                "expected_reason":
                    "ordinary",
            }

            continue

        # ----------------------------------------------------
        # Collision group.
        #
        # We only accept this automatically for POST pages.
        # ----------------------------------------------------

        collision_groups[
            logical_path
        ] = rows

        for row in rows:

            node_type = (
                row.get(
                    "type",
                    "",
                ).strip()
            )

            if node_type != "post":

                raise RuntimeError(
                    "Unexpected non-post collision:\n"
                    f"{logical_path}"
                )

            original = Path(
                row[
                    "local_path_clean"
                ]
            )

            post_id = post_id_from_url(
                row.get(
                    "url",
                    "",
                )
            )

            if not post_id:

                raise RuntimeError(
                    "Could not derive POST ID for:\n"
                    f"{row.get('url', '')}"
                )

            repaired_name = (
                f"{original.stem} "
                f"[{post_id}]"
                f"{original.suffix}"
            )

            repaired_path = (
                original.parent
                / repaired_name
            )

            repaired_key = nfc(
                str(
                    repaired_path
                )
            )

            expected[
                repaired_key
            ] = {
                "type":
                    node_type,
                "title":
                    row.get(
                        "title",
                        "",
                    ),
                "url":
                    row.get(
                        "url",
                        "",
                    ),
                "parent_url":
                    row.get(
                        "parent_url",
                        "",
                    ),
                "original_local_path":
                    str(
                        original
                    ),
                "expected_reason":
                    "collision_repaired",
                "post_id":
                    post_id,
            }

    return (
        expected,
        collision_groups,
    )


# ============================================================
# SCAN ACTUAL FILESYSTEM
# ============================================================

def scan_archive():

    html_files = []
    htm_files = []
    mp4_files = []
    zip_files = []
    other_files = []

    for path in ARCHIVE_ROOT.rglob("*"):

        if not path.is_file():
            continue

        suffix = path.suffix.lower()

        if suffix == ".html":

            html_files.append(path)

        elif suffix == ".htm":

            htm_files.append(path)

        elif suffix == ".mp4":

            mp4_files.append(path)

        elif suffix == ".zip":

            zip_files.append(path)

        else:

            other_files.append(path)

    return (
        html_files,
        htm_files,
        mp4_files,
        zip_files,
        other_files,
    )


# ============================================================
# MATCH ACTUAL FILES
# ============================================================

def build_actual_html_map(
    html_files: list[Path],
) -> dict[str, list[Path]]:

    result = defaultdict(list)

    for path in html_files:

        result[
            actual_relative(path)
        ].append(
            path
        )

    return result


# ============================================================
# MAIN AUDIT
# ============================================================

def main():

    print("=" * 78)
    print(
        "VFX APPRENTICE FINAL ARCHIVE AUDIT"
    )
    print("=" * 78)

    print()
    print(
        "READ-ONLY"
    )

    print(
        "No files will be modified."
    )

    print(
        "No files will be deleted."
    )

    print()

    if not ARCHIVE_ROOT.exists():

        raise FileNotFoundError(
            f"Archive root not found:\n"
            f"{ARCHIVE_ROOT}"
        )

    tree_rows = load_csv(
        TREE_REPORT
    )

    html_rows = load_csv(
        HTML_REPORT
    )

    print(
        f"Discovery rows: "
        f"{len(tree_rows)}"
    )

    print(
        f"HTML report rows: "
        f"{len(html_rows)}"
    )

    # --------------------------------------------------------
    # Expected logical page set.
    # --------------------------------------------------------

    (
        expected,
        collision_groups,
    ) = build_expected_pages(
        tree_rows
    )

    print()
    print(
        f"Discovered URLs/pages: "
        f"{len([r for r in tree_rows if r.get('status','').strip() == 'DISCOVERED'])}"
    )

    print(
        f"Expected final HTML files: "
        f"{len(expected)}"
    )

    print(
        f"Collision groups: "
        f"{len(collision_groups)}"
    )

    collision_original_count = sum(
        len(rows)
        for rows in collision_groups.values()
    )

    if collision_groups:

        print(
            f"Pages participating in collisions: "
            f"{collision_original_count}"
        )

    # --------------------------------------------------------
    # Filesystem scan.
    # --------------------------------------------------------

    print()
    print(
        "Scanning archive..."
    )

    (
        actual_html,
        actual_htm,
        actual_mp4,
        actual_zip,
        actual_other,
    ) = scan_archive()

    actual_html_map = (
        build_actual_html_map(
            actual_html
        )
    )

    # --------------------------------------------------------
    # Expected HTML verification.
    # --------------------------------------------------------

    missing = []
    zero_byte = []
    present = []

    audit_rows = []

    for logical_path, info in (
        expected.items()
    ):

        candidates = (
            actual_html_map.get(
                logical_path,
                []
            )
        )

        if not candidates:

            missing.append(
                logical_path
            )

            audit_rows.append({
                "category":
                    "expected_html",
                "type":
                    info["type"],
                "title":
                    info["title"],
                "url":
                    info["url"],
                "local_path":
                    logical_path,
                "status":
                    "MISSING",
                "size_bytes":
                    0,
            })

            continue

        # More than one physically distinct file with the
        # same normalized logical path is also a problem.
        if len(candidates) > 1:

            for candidate in candidates:

                size = candidate.stat().st_size

                status = (
                    "DUPLICATE_PHYSICAL_PATH"
                    if size > 0
                    else "DUPLICATE_ZERO_BYTE"
                )

                audit_rows.append({
                    "category":
                        "duplicate_html",
                    "type":
                        info["type"],
                    "title":
                        info["title"],
                    "url":
                        info["url"],
                    "local_path":
                        actual_relative(
                            candidate
                        ),
                    "status":
                        status,
                    "size_bytes":
                        size,
                })

            continue

        target = candidates[0]
        size = target.stat().st_size

        if size == 0:

            zero_byte.append(
                logical_path
            )

            status = "ZERO_BYTE"

        else:

            present.append(
                logical_path
            )

            status = "PRESENT"

        audit_rows.append({
            "category":
                "expected_html",
            "type":
                info["type"],
            "title":
                info["title"],
            "url":
                info["url"],
            "local_path":
                logical_path,
            "status":
                status,
            "size_bytes":
                size,
        })

    # --------------------------------------------------------
    # Detect unexpected HTML after Unicode normalization.
    # --------------------------------------------------------

    expected_set = set(
        expected.keys()
    )

    unexpected = []

    for logical_path, candidates in (
        actual_html_map.items()
    ):

        if logical_path in expected_set:
            continue

        for path in candidates:

            unexpected.append(
                logical_path
            )

            audit_rows.append({
                "category":
                    "unexpected_html",
                "type":
                    "",
                "title":
                    "",
                "url":
                    "",
                "local_path":
                    logical_path,
                "status":
                    "UNEXPECTED",
                "size_bytes":
                    path.stat().st_size,
            })

    # --------------------------------------------------------
    # .htm files.
    # --------------------------------------------------------

    for path in actual_htm:

        audit_rows.append({
            "category":
                "legacy_html",
            "type":
                "",
            "title":
                "",
            "url":
                "",
            "local_path":
                actual_relative(path),
            "status":
                "HTM_LEFTOVER",
            "size_bytes":
                path.stat().st_size,
        })

    # --------------------------------------------------------
    # MP4 / ZIP.
    # --------------------------------------------------------

    mp4_size = sum(
        path.stat().st_size
        for path in actual_mp4
    )

    zip_size = sum(
        path.stat().st_size
        for path in actual_zip
    )

    # --------------------------------------------------------
    # Historical MP4 inventory.
    # --------------------------------------------------------

    historical_mp4_count = None

    if MP4_INVENTORY.exists():

        try:

            inventory = load_csv(
                MP4_INVENTORY
            )

            historical_mp4_count = (
                len(inventory)
            )

        except Exception:
            historical_mp4_count = None

    # --------------------------------------------------------
    # HTML report historical statuses.
    # --------------------------------------------------------

    report_statuses = Counter(
        row.get(
            "status",
            "",
        ).strip()
        for row in html_rows
    )

    # --------------------------------------------------------
    # Logical completeness.
    # --------------------------------------------------------

    complete = (
        len(expected)
        == len(present)
        and not missing
        and not zero_byte
        and not unexpected
        and not actual_htm
        and not collision_groups
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # collision_groups describes the ORIGINAL report,
    # not the FINAL repaired filesystem.
    #
    # Because we have now transformed every collision into
    # a unique [POST_ID] path, those original collisions should
    # not make the final audit fail.
    # --------------------------------------------------------

    final_collision_count = 0

    # Detect duplicate physical normalized paths.
    for logical_path, candidates in (
        actual_html_map.items()
    ):

        if len(candidates) > 1:
            final_collision_count += 1

    complete = (
        len(expected)
        == len(present)
        and not missing
        and not zero_byte
        and not unexpected
        and not actual_htm
        and final_collision_count == 0
    )

    # --------------------------------------------------------
    # Write CSV.
    # --------------------------------------------------------

    with AUDIT_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        fields = [
            "category",
            "type",
            "title",
            "url",
            "local_path",
            "status",
            "size_bytes",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        writer.writerows(
            audit_rows
        )

    # --------------------------------------------------------
    # Summary.
    # --------------------------------------------------------

    with SUMMARY_REPORT.open(
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "VFX APPRENTICE FINAL ARCHIVE AUDIT\n"
        )

        f.write(
            "=" * 78
            + "\n\n"
        )

        f.write(
            f"Archive: {ARCHIVE_ROOT}\n\n"
        )

        f.write(
            f"Discovered URLs: "
            f"{len([r for r in tree_rows if r.get('status','').strip() == 'DISCOVERED'])}\n"
        )

        f.write(
            f"Expected final HTML: "
            f"{len(expected)}\n"
        )

        f.write(
            f"Present HTML: "
            f"{len(present)}\n"
        )

        f.write(
            f"Missing HTML: "
            f"{len(missing)}\n"
        )

        f.write(
            f"Zero-byte HTML: "
            f"{len(zero_byte)}\n"
        )

        f.write(
            f"Unexpected HTML: "
            f"{len(unexpected)}\n"
        )

        f.write(
            f".htm leftovers: "
            f"{len(actual_htm)}\n"
        )

        f.write(
            f"Final duplicate normalized paths: "
            f"{final_collision_count}\n"
        )

        f.write(
            "\n"
        )

        f.write(
            "MEDIA\n"
        )

        f.write(
            f"MP4 files: "
            f"{len(actual_mp4)}\n"
        )

        f.write(
            f"MP4 size: "
            f"{human_size(mp4_size)}\n"
        )

        f.write(
            f"ZIP files: "
            f"{len(actual_zip)}\n"
        )

        f.write(
            f"ZIP size: "
            f"{human_size(zip_size)}\n"
        )

        if historical_mp4_count is not None:

            f.write(
                f"Historical MP4 count: "
                f"{historical_mp4_count}\n"
            )

            f.write(
                f"MP4 count difference: "
                f"{len(actual_mp4) - historical_mp4_count}\n"
            )

        f.write(
            "\n"
        )

        f.write(
            "ORIGINAL DOWNLOAD REPORT STATUSES\n"
        )

        for status, count in sorted(
            report_statuses.items()
        ):

            f.write(
                f"{status}: {count}\n"
            )

        if missing:

            f.write(
                "\nMISSING HTML:\n"
            )

            for path in missing:

                f.write(
                    f"  {path}\n"
                )

        if zero_byte:

            f.write(
                "\nZERO-BYTE HTML:\n"
            )

            for path in zero_byte:

                f.write(
                    f"  {path}\n"
                )

        if unexpected:

            f.write(
                "\nUNEXPECTED HTML:\n"
            )

            for path in unexpected:

                f.write(
                    f"  {path}\n"
                )

        if actual_htm:

            f.write(
                "\n.HTM LEFTOVERS:\n"
            )

            for path in actual_htm:

                f.write(
                    f"  {actual_relative(path)}\n"
                )

        f.write(
            "\nRESULT:\n"
        )

        if complete:

            f.write(
                "PASS — final HTML archive is complete.\n"
            )

        else:

            f.write(
                "REVIEW REQUIRED.\n"
            )

    # --------------------------------------------------------
    # Terminal output.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        "FINAL AUDIT COMPLETE"
    )
    print("=" * 78)

    print()
    print(
        "HTML"
    )

    print(
        f"  Expected final HTML : "
        f"{len(expected)}"
    )

    print(
        f"  Present             : "
        f"{len(present)}"
    )

    print(
        f"  Missing             : "
        f"{len(missing)}"
    )

    print(
        f"  Zero-byte           : "
        f"{len(zero_byte)}"
    )

    print(
        f"  Unexpected          : "
        f"{len(unexpected)}"
    )

    print(
        f"  .htm leftovers      : "
        f"{len(actual_htm)}"
    )

    print(
        f"  Duplicate paths     : "
        f"{final_collision_count}"
    )

    print()
    print(
        "MEDIA"
    )

    print(
        f"  MP4: "
        f"{len(actual_mp4)} files / "
        f"{human_size(mp4_size)}"
    )

    print(
        f"  ZIP: "
        f"{len(actual_zip)} files / "
        f"{human_size(zip_size)}"
    )

    if historical_mp4_count is not None:

        print()
        print(
            "MP4 INVENTORY"
        )

        print(
            f"  Historical : "
            f"{historical_mp4_count}"
        )

        print(
            f"  Current    : "
            f"{len(actual_mp4)}"
        )

        print(
            f"  Difference : "
            f"{len(actual_mp4) - historical_mp4_count}"
        )

    print()
    print(
        "RESULT"
    )

    if complete:

        print(
            "  PASS — 692-page logical mirror is complete."
        )

    else:

        print(
            "  REVIEW REQUIRED."
        )

    print()
    print(
        "Reports:"
    )

    print(
        f"  {AUDIT_REPORT.resolve()}"
    )

    print(
        f"  {SUMMARY_REPORT.resolve()}"
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
            "Audit cancelled."
        )

        sys.exit(130)

    except Exception as exc:

        print()
        print(
            "=" * 78
        )
        print(
            "AUDIT ERROR"
        )
        print("=" * 78)

        print(
            str(exc)
        )

        sys.exit(1)