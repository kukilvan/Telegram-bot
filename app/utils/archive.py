"""The encrypted archive of a copy of the database: one file in a `.7z`, LZMA2 with AES-256 and the names hidden, that 7-Zip opens by the password.

Made with `py7zr` (spec 4.4 of stage 7.1, step 1; `.scratch/7-1-backups-export/checks.md`, 1): the copy goes in under its
own name, the header is encrypted too, so without the password neither the content nor the name can be read. The 7z
format turns the password into UTF-16LE, so a Cyrillic password opens the archive in 7-Zip for Windows as well.
Blocking work: the core calls it in a worker thread.
"""

from pathlib import Path

import py7zr

ARCHIVE_SUFFIX = ".7z"
FILTERS = [{"id": py7zr.FILTER_LZMA2, "preset": 9}, {"id": py7zr.FILTER_CRYPTO_AES256_SHA256}]


def archive_name(copy: Path) -> str:
    """`tracker_db_20261108_163000_manual.db` → `tracker_db_20261108_163000_manual.7z`."""
    return copy.stem + ARCHIVE_SUFFIX


def make_archive(copy: Path, target: Path, password: str) -> Path:
    """The archive `target` of the file `copy` under the password; a file left at `target` from before is replaced.
    A failure leaves no half-made archive."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        with py7zr.SevenZipFile(target, "w", password=password, header_encryption=True, filters=FILTERS) as archive:
            archive.write(copy, copy.name)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target
