"""Copy local data files into the Zetaris file store of a local Docker install, so Zetaris can register them.

Usage:  .venv\\Scripts\\python scripts\\upload_filestore.py [FILE ...] [--folder factsync] [--dry-run]
Default files: data/official/*.csv. Prints the file-store root to use in zetaris/*.sql (ZETARIS_FILESTORE_ROOT).

Zetaris can't read files on the host; the file store lives inside the driver container at
/home/zetaris/customer-data/<org id>/file-store. A local install has a single organisation folder,
which this script finds by itself (override with ZETARIS_FILESTORE_ROOT).
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUSTOMER_DATA = "/home/zetaris/customer-data"


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"docker {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def filestore_root(container):
    if os.environ.get("ZETARIS_FILESTORE_ROOT"):
        return os.environ["ZETARIS_FILESTORE_ROOT"].rstrip("/")
    orgs = [d for d in docker("exec", container, "ls", CUSTOMER_DATA).split() if re.fullmatch(r"[0-9a-f]{32}", d)]
    if len(orgs) != 1:
        sys.exit(f"expected one organisation folder in {CUSTOMER_DATA}, found {orgs}; set ZETARIS_FILESTORE_ROOT")
    return f"{CUSTOMER_DATA}/{orgs[0]}/file-store"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--container", default="zetaris-driver-1")
    parser.add_argument("--folder", default="factsync")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files = args.files or sorted((ROOT / "data" / "official").glob("*.csv"))
    root = filestore_root(args.container)
    target = f"{root}/{args.folder}"
    for file in files:
        print(f"{'would copy' if args.dry_run else 'copy'} {file.name} -> {args.container}:{target}/")
    if args.dry_run:
        print(f"ZETARIS_FILESTORE_ROOT={root}")
        return
    docker("exec", "-u", "zetaris", args.container, "mkdir", "-p", target)
    for file in files:
        docker("cp", str(file), f"{args.container}:{target}/{file.name}")
        docker("exec", "-u", "0", args.container, "chown", "zetaris:zetaris", f"{target}/{file.name}")
    print(docker("exec", args.container, "ls", "-l", target).strip())
    print(f"ZETARIS_FILESTORE_ROOT={root}")


if __name__ == "__main__":
    main()
