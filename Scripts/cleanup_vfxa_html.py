#!/usr/bin/env python3

"""
VFX Apprentice HTML Cleanup

SAFETY:
    This script ONLY deletes files ending in:
        .html
        .htm

    It does NOT delete, move, rename, or modify:
        .mp4
        .zip
        .rar
        .7z
        .pdf
        images
        folders
        or any other file types.

TARGET:
    vfx_apprentice_downloads/
"""

from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "vfx_apprentice_downloads"
)

TARGET_EXTENSIONS = {
    ".html",
    ".htm",
}


# ============================================================
# HELPERS
# ============================================================

def human_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]

    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"

        size /= 1024

    return f"{size_bytes} B"


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 78)
    print("VFX APPRENTICE HTML CLEANUP")
    print("=" * 78)

    print()
    print("TARGET:")
    print(f"  {BASE_DIR}")

    print()
    print("FILES THAT WILL BE DELETED:")
    print("  *.html")
    print("  *.htm")

    print()
    print("FILES THAT WILL NOT BE TOUCHED:")
    print("  *.mp4")
    print("  *.zip")
    print("  *.rar")
    print("  *.7z")
    print("  *.pdf")
    print("  images")
    print("  folders")
    print("  every other file type")

    if not BASE_DIR.exists():
        raise FileNotFoundError(
            f"Target directory does not exist:\n{BASE_DIR}"
        )

    if not BASE_DIR.is_dir():
        raise NotADirectoryError(
            f"Target path is not a directory:\n{BASE_DIR}"
        )

    # --------------------------------------------------------
    # Find targets first.
    # --------------------------------------------------------

    html_files = []

    for path in BASE_DIR.rglob("*"):

        if not path.is_file():
            continue

        if path.suffix.lower() in TARGET_EXTENSIONS:
            html_files.append(path)

    html_files.sort(
        key=lambda p: str(p).lower()
    )

    print()
    print(
        f"HTML files found: {len(html_files)}"
    )

    if not html_files:
        print()
        print("Nothing to delete.")
        return

    total_size = 0

    for path in html_files:
        try:
            total_size += path.stat().st_size
        except OSError:
            pass

    print(
        f"Total HTML size: {human_size(total_size)}"
    )

    # --------------------------------------------------------
    # Show exactly what will be removed.
    # --------------------------------------------------------

    print()
    print("-" * 78)
    print("FILES TO DELETE")
    print("-" * 78)

    for index, path in enumerate(
        html_files,
        start=1,
    ):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        try:
            relative = path.relative_to(
                BASE_DIR
            )
        except ValueError:
            relative = path

        print(
            f"{index:04d} | "
            f"{human_size(size):>10} | "
            f"{relative}"
        )

    # --------------------------------------------------------
    # Confirmation.
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print(
        f"ABOUT TO DELETE {len(html_files)} HTML FILE(S)"
    )
    print(
        f"TOTAL SIZE: {human_size(total_size)}"
    )
    print("=" * 78)

    confirmation = input(
        '\nType DELETE to continue: '
    ).strip()

    if confirmation != "DELETE":
        print()
        print(
            "Cancelled. No files were deleted."
        )
        return

    # --------------------------------------------------------
    # Delete only HTML files.
    # --------------------------------------------------------

    deleted = 0
    failed = 0
    deleted_bytes = 0

    for path in html_files:

        try:

            size = path.stat().st_size

            path.unlink()

            deleted += 1
            deleted_bytes += size

            try:
                relative = path.relative_to(
                    BASE_DIR
                )
            except ValueError:
                relative = path

            print(
                f"DELETED | {relative}"
            )

        except OSError as exc:

            failed += 1

            print()
            print(
                f"FAILED  | {path}"
            )
            print(
                f"          {exc}"
            )

    # --------------------------------------------------------
    # Final verification.
    # --------------------------------------------------------

    remaining = []

    for path in BASE_DIR.rglob("*"):

        if not path.is_file():
            continue

        if path.suffix.lower() in TARGET_EXTENSIONS:
            remaining.append(path)

    print()
    print("=" * 78)
    print("CLEANUP COMPLETE")
    print("=" * 78)

    print()
    print(
        f"Deleted HTML files : {deleted}"
    )

    print(
        f"Failed deletions   : {failed}"
    )

    print(
        f"Deleted size       : "
        f"{human_size(deleted_bytes)}"
    )

    print(
        f"HTML files remaining: "
        f"{len(remaining)}"
    )

    if remaining:

        print()
        print(
            "WARNING: Some HTML files remain:"
        )

        for path in remaining:
            print(
                f"  {path}"
            )

    else:

        print()
        print(
            "Verified: no .html or .htm files remain."
        )

    print()
    print(
        "No MP4 or ZIP files were targeted by this script."
    )


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print()
        print(
            "Cancelled by user."
        )

    except Exception as exc:

        print()
        print("=" * 78)
        print("ERROR")
        print("=" * 78)
        print(
            str(exc)
        )
