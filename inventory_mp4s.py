#!/usr/bin/env python3

from pathlib import Path
import csv
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(
    "/Users/haitamhamdan/Library/CloudStorage/"
    "GoogleDrive-haitam.hamdan95@gmail.com/My Drive/"
    "vfx_apprentice_downloads"
)

OUTPUT_TXT = Path("vfx_apprentice_mp4_inventory.txt")
OUTPUT_CSV = Path("vfx_apprentice_mp4_inventory.csv")


# ============================================================
# HELPERS
# ============================================================

def format_size(size_bytes: int) -> str:
    """Convert bytes into a human-readable size."""
    units = ["B", "KB", "MB", "GB", "TB"]

    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size_bytes} B"


def scan_mp4_files(base_dir: Path):
    """Recursively locate every MP4 file."""
    if not base_dir.exists():
        raise FileNotFoundError(
            f"Directory does not exist:\n{base_dir}\n\n"
            "Check BASE_DIR in the script."
        )

    if not base_dir.is_dir():
        raise NotADirectoryError(
            f"BASE_DIR is not a directory:\n{base_dir}"
        )

    files = []

    for path in base_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".mp4":
            try:
                stat = path.stat()
                relative_path = path.relative_to(base_dir)

                files.append({
                    "filename": path.name,
                    "relative_path": str(relative_path),
                    "size_bytes": stat.st_size,
                    "size_human": format_size(stat.st_size),
                })

            except OSError as exc:
                print(f"WARNING: Could not inspect {path}: {exc}")

    # Sort alphabetically by path
    files.sort(key=lambda item: item["relative_path"].lower())

    return files


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("VFX APPRENTICE MP4 INVENTORY")
    print("=" * 70)

    print(f"\nScanning:")
    print(BASE_DIR)

    files = scan_mp4_files(BASE_DIR)

    total_bytes = sum(item["size_bytes"] for item in files)

    print("\nScan complete.")
    print(f"MP4 files found : {len(files)}")
    print(f"Total size      : {format_size(total_bytes)}")

    # --------------------------------------------------------
    # TXT INVENTORY
    # --------------------------------------------------------

    with OUTPUT_TXT.open("w", encoding="utf-8") as f:
        f.write("VFX APPRENTICE MP4 INVENTORY\n")
        f.write("=" * 70 + "\n")
        f.write(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"Base directory: {BASE_DIR}\n")
        f.write(f"MP4 count: {len(files)}\n")
        f.write(f"Total size: {format_size(total_bytes)}\n")
        f.write("\n")
        f.write("=" * 70 + "\n\n")

        for index, item in enumerate(files, start=1):
            f.write(
                f"{index:04d} | "
                f"{item['size_human']:>10} | "
                f"{item['relative_path']}\n"
            )

    # --------------------------------------------------------
    # CSV INVENTORY
    # --------------------------------------------------------

    with OUTPUT_CSV.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "index",
                "filename",
                "relative_path",
                "size_bytes",
                "size_human",
            ],
        )

        writer.writeheader()

        for index, item in enumerate(files, start=1):
            writer.writerow({
                "index": index,
                "filename": item["filename"],
                "relative_path": item["relative_path"],
                "size_bytes": item["size_bytes"],
                "size_human": item["size_human"],
            })

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("\nFiles created:")
    print(f"  {OUTPUT_TXT.resolve()}")
    print(f"  {OUTPUT_CSV.resolve()}")

    print("\nFirst 20 files:")
    print("-" * 70)

    for index, item in enumerate(files[:20], start=1):
        print(
            f"{index:04d} | "
            f"{item['size_human']:>10} | "
            f"{item['relative_path']}"
        )

    if len(files) > 20:
        print(f"\n... and {len(files) - 20} more files.")

    print("\nDone.")


if __name__ == "__main__":
    main()