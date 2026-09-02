"""Download and unpack the public datasets into data/raw/.

Everything it writes is gitignored. Nothing here is committed.

    python phase5/fetch_datasets.py --list
    python phase5/fetch_datasets.py --dataset uci_har
    python phase5/fetch_datasets.py --dataset shimfall,uci_har
    python phase5/fetch_datasets.py --all

Downloads are slow and the hosts are not always up, so each dataset is
independent: a failure on one does not stop the others, and re-running skips
anything already unpacked.

REACHABILITY, as measured on 2026-09-02
---------------------------------------
    uci_har   OK    ~61 MB, but slow (~30 KB/s observed)
    shimfall  OK    ~1.4 MB
    wisdm     OK    ~11 MB
    ravdess   OK    ~199 MB, audio only
    sisfall   DOWN  sistemic.udea.edu.co refuses connections

SisFall was the originally-planned source of real falls. ShimFall&ADL
replaces it: same role (falls + ADLs), reachable, and at the device's 50 Hz.
"""

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
DOWNLOAD_DIR = RAW_DIR / "_downloads"

DATASETS = {
    "uci_har": {
        "url": (
            "https://archive.ics.uci.edu/static/public/240/"
            "human+activity+recognition+using+smartphones.zip"
        ),
        "archive": "uci_har.zip",
        "target": "uci_har",
        "nested": "UCI HAR Dataset.zip",
        "role": "real negatives (ADLs only), 50 Hz, 30 subjects",
        "licence": "UCI ML Repository terms; cite Anguita et al., ESANN 2013",
        "size_mb": 61
    },
    "shimfall": {
        "url": "https://zenodo.org/records/3901285/files/Data.zip?download=1",
        "archive": "shimfall.zip",
        "target": "shimfall",
        "nested": None,
        "role": "real falls AND ADLs, 50 Hz, 35 subjects",
        "licence": "CC-BY-NC-ND-4.0; cite Althobaiti et al., Sensors 2020",
        "size_mb": 1.4
    },
    "wisdm": {
        "url": (
            "https://www.cis.fordham.edu/wisdm/includes/datasets/latest/"
            "WISDM_ar_latest.tar.gz"
        ),
        "archive": "wisdm.tar.gz",
        "target": "wisdm",
        "nested": None,
        "role": "extra negatives, 20 Hz (weaker - needs upsampling)",
        "licence": "WISDM terms; cite Kwapisz et al., 2010",
        "size_mb": 11
    },
    "ravdess": {
        "url": (
            "https://zenodo.org/records/1188976/files/"
            "Audio_Speech_Actors_01-24.zip"
        ),
        "archive": "ravdess.zip",
        "target": "ravdess",
        "nested": None,
        "role": "audio only - calibrates the loud end of AudioEnergy",
        "licence": "CC-BY-NC-SA-4.0; cite Livingstone & Russo, 2018",
        "size_mb": 199
    }
}

# Kept so the failure is documented rather than silently missing.
UNREACHABLE = {
    "sisfall": (
        "sistemic.udea.edu.co refuses connections (checked 2026-09-02). "
        "Use --dataset shimfall instead: same role, reachable, 50 Hz."
    )
}


def _download(url, destination):
    """Stream to a .part file, then rename - so a partial file is never
    mistaken for a complete one by a later run."""

    partial = destination.with_suffix(destination.suffix + ".part")

    def report(count, block_size, total):
        if total <= 0:
            return

        done = min(count * block_size, total)
        percent = 100.0 * done / total

        sys.stdout.write(
            f"\r    {done / 1048576:7.1f} / {total / 1048576:.1f} MB "
            f"({percent:5.1f}%)"
        )
        sys.stdout.flush()

    urllib.request.urlretrieve(url, partial, reporthook=report)
    sys.stdout.write("\n")

    partial.replace(destination)


def _unpack(archive, target, nested):
    target.mkdir(parents=True, exist_ok=True)

    if archive.suffixes[-2:] == [".tar", ".gz"] or archive.suffix == ".tgz":
        shutil.unpack_archive(str(archive), str(target))
        return

    with zipfile.ZipFile(archive) as bundle:
        members = [
            name for name in bundle.namelist()
            if not name.startswith("__MACOSX") and ".DS_Store" not in name
        ]
        bundle.extractall(target, members=members)

    if not nested:
        return

    # UCI ships a zip inside a zip
    inner = next(target.rglob(nested), None)

    if inner is None:
        raise RuntimeError(f"expected nested archive {nested} inside {archive}")

    with zipfile.ZipFile(inner) as bundle:
        members = [
            name for name in bundle.namelist()
            if not name.startswith("__MACOSX") and ".DS_Store" not in name
        ]
        bundle.extractall(target, members=members)

    inner.unlink()


def fetch(name, force=False):
    if name in UNREACHABLE:
        print(f"  {name}: UNAVAILABLE - {UNREACHABLE[name]}")
        return False

    spec = DATASETS[name]

    target = RAW_DIR / spec["target"]

    if target.exists() and any(target.iterdir()) and not force:
        print(f"  {name}: already unpacked at {target} (use --force to redo)")
        return True

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    archive = DOWNLOAD_DIR / spec["archive"]

    print(f"  {name}: {spec['role']}")
    print(f"    licence: {spec['licence']}")

    try:
        if not archive.exists() or force:
            print(f"    downloading ~{spec['size_mb']} MB ...")
            _download(spec["url"], archive)
        else:
            print(f"    using cached {archive.name}")

        print("    unpacking ...")
        _unpack(archive, target, spec["nested"])

    except Exception as error:                          # noqa: BLE001
        print(f"    FAILED: {type(error).__name__}: {error}")
        print(
            f"    You can download it by hand from:\n"
            f"      {spec['url']}\n"
            f"    and unpack it into {target}"
        )
        return False

    print(f"    ready: {target}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", help="comma-separated names")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download and re-unpack even if present"
    )
    arguments = parser.parse_args()

    if arguments.list or not (arguments.dataset or arguments.all):
        print("\nAvailable datasets:\n")

        for name, spec in DATASETS.items():
            target = RAW_DIR / spec["target"]
            state = (
                "present"
                if target.exists() and any(target.iterdir())
                else "not fetched"
            )
            print(f"  {name:10s} [{state:11s}] ~{spec['size_mb']:>5} MB  "
                  f"{spec['role']}")

        for name, reason in UNREACHABLE.items():
            print(f"  {name:10s} [UNREACHABLE ] {reason}")

        print(
            "\nNothing here is committed - data/raw/ is gitignored.\n"
            "See DATA_REQUIREMENTS.md for what each corpus can and cannot "
            "prove.\n"
        )
        return

    names = (
        list(DATASETS)
        if arguments.all
        else [n.strip() for n in arguments.dataset.split(",") if n.strip()]
    )

    unknown = [
        name for name in names
        if name not in DATASETS and name not in UNREACHABLE
    ]

    if unknown:
        parser.error(
            f"unknown dataset(s) {unknown}; known: {sorted(DATASETS)}"
        )

    print("\nFetching into data/raw/ (gitignored)\n")

    results = {name: fetch(name, force=arguments.force) for name in names}

    print("\nSummary:")

    for name, ok in results.items():
        print(f"  {name:10s} {'OK' if ok else 'FAILED'}")

    print("\nConfirm with: python phase5/dataset_adapters.py\n")

    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
