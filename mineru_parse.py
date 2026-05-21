#!/usr/bin/env python3
"""
MinerU batch PDF parser — local CLI (macOS / Linux).

Flow: auto-split large PDFs -> request signed upload URLs -> PUT local files -> poll batch -> download & unzip.

Setup
-----
    pip install requests tqdm pypdf
    export MINERU_API_KEY="your_token_here"

Usage
-----
    python mineru_parse.py ./folder/
    python mineru_parse.py report.pdf --pages 1-50 --out results
    python mineru_parse.py doc.pdf --model pipeline --formula

Notes
-----
* Token is read from $MINERU_API_KEY. Never hardcode it.
* Limits: 200 MB / 200 pages per file, 50 files per batch, 1000 pages/day priority quota.
* PDFs >200 pages are auto-split into chunks before upload.
"""

import argparse
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm
from pypdf import PdfReader, PdfWriter

BASE = "https://mineru.net/api/v4"
MAX_BATCH = 50
PAGE_LIMIT = 200


def get_headers() -> dict:
    token = os.environ.get("MINERU_API_KEY")
    if not token:
        sys.exit("ERROR: set the MINERU_API_KEY environment variable first.\n"
                 '  export MINERU_API_KEY="your_token_here"')
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def collect_pdfs(inputs) -> list:
    paths = []
    for item in inputs:
        p = Path(item).expanduser()
        if p.is_dir():
            paths.extend(sorted(p.glob("*.pdf")))
        elif p.is_file():
            paths.append(p)
        else:
            print(f"  skipped (not found): {item}")
    seen, unique = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def split_pdf(path: Path, tmp_dir: Path) -> list:
    """Split a PDF into PAGE_LIMIT-page chunks. Returns list of chunk paths."""
    reader = PdfReader(str(path))
    total = len(reader.pages)
    if total <= PAGE_LIMIT:
        return [path]

    chunks = []
    for i, start in enumerate(range(0, total, PAGE_LIMIT)):
        end = min(start + PAGE_LIMIT, total)
        writer = PdfWriter()
        for page_num in range(start, end):
            writer.add_page(reader.pages[page_num])
        chunk_path = tmp_dir / f"{path.stem}_part{i+1:03d}.pdf"
        with open(chunk_path, "wb") as f:
            writer.write(f)
        chunks.append(chunk_path)
        print(f"  split: {path.name} -> {chunk_path.name} (pages {start+1}-{end})")
    return chunks


def prepare_paths(paths: list, out_dir: Path) -> list:
    """Expand any >200-page PDFs into chunks."""
    tmp_dir = out_dir / "_chunks"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    expanded = []
    for p in paths:
        chunks = split_pdf(p, tmp_dir)
        expanded.extend(chunks)
    return expanded


def make_data_id(path: Path) -> str:
    return path.stem


def submit_batch(paths: list, opts: dict, headers: dict) -> tuple:
    files_meta = [{"name": p.name, "data_id": make_data_id(p)} for p in paths]
    if opts.get("page_ranges"):
        for fm in files_meta:
            fm["page_ranges"] = opts["page_ranges"]

    body = {
        "model_version": opts["model_version"],
        "enable_table": opts["enable_table"],
        "enable_formula": opts["enable_formula"],
        "language": opts["language"],
        "files": files_meta,
    }

    resp = requests.post(f"{BASE}/file-urls/batch", headers=headers, json=body)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        sys.exit(f"API error requesting upload URLs: {payload}")

    batch_id = payload["data"]["batch_id"]
    upload_urls = payload["data"]["file_urls"]
    print(f"batch_id: {batch_id}")

    for path, url in zip(paths, upload_urls):
        with open(path, "rb") as f:
            put = requests.put(url, data=f)
            put.raise_for_status()
        print(f"  uploaded: {path.name}")

    print("All files uploaded — parse tasks auto-started.")
    return batch_id, upload_urls


def poll_batch(batch_id: str, headers: dict, interval: int = 5, max_wait: int = 1800) -> list:
    start = time.time()
    bar = tqdm(desc="parsing", unit="poll")
    while True:
        r = requests.get(f"{BASE}/extract-results/batch/{batch_id}", headers=headers)
        r.raise_for_status()
        results = r.json()["data"]["extract_result"]
        done = sum(1 for f in results if f["state"] in ("done", "failed"))
        bar.set_postfix(done=f"{done}/{len(results)}")
        bar.update(1)
        if done == len(results):
            bar.close()
            return results
        if time.time() - start > max_wait:
            bar.close()
            raise TimeoutError(f"Batch exceeded max_wait ({max_wait}s). batch_id={batch_id}")
        time.sleep(interval)


def fetch_result(f: dict, out_dir: Path):
    if f["state"] != "done":
        return None
    dest = out_dir / f.get("data_id", f.get("file_name", "unknown"))
    dest.mkdir(parents=True, exist_ok=True)
    blob = requests.get(f["full_zip_url"]).content
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(dest)
    return dest


def chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    ap = argparse.ArgumentParser(description="MinerU batch PDF parser (local CLI).")
    ap.add_argument("inputs", nargs="+", help="PDF files and/or directories of PDFs")
    ap.add_argument("--out", default="mineru_out", help="output directory (default: mineru_out)")
    ap.add_argument("--model", default="vlm", choices=["vlm", "pipeline"],
                    help="model_version (default: vlm)")
    ap.add_argument("--lang", default="en", help="document language (default: en)")
    ap.add_argument("--no-table", action="store_true", help="disable table recognition")
    ap.add_argument("--formula", action="store_true", help="enable formula recognition")
    ap.add_argument("--pages", default=None,
                    help='page range applied to every file, e.g. "1-50"')
    ap.add_argument("--preview", type=int, default=2000,
                    help="chars of full.md to print for the first done doc (0 = off)")
    args = ap.parse_args()

    headers = get_headers()
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_paths = collect_pdfs(args.inputs)
    if not raw_paths:
        sys.exit("No PDFs found in the given inputs.")

    print(f"Found {len(raw_paths)} file(s) — checking page counts and splitting if needed...")
    paths = prepare_paths(raw_paths, out_dir)

    print(f"\nQueued {len(paths)} file(s) for upload:")
    for p in paths:
        size_mb = p.stat().st_size / 1e6
        flag = "  ⚠ >200MB" if size_mb > 200 else ""
        print(f"  - {p.name} ({size_mb:.1f} MB){flag}")

    opts = {
        "model_version": args.model,
        "enable_table": not args.no_table,
        "enable_formula": args.formula,
        "language": args.lang,
        "page_ranges": args.pages,
    }

    all_results = []
    batches = list(chunked(paths, MAX_BATCH))
    for i, group in enumerate(batches, 1):
        if len(batches) > 1:
            print(f"\n=== Batch {i}/{len(batches)} ({len(group)} files) ===")
        batch_id, _ = submit_batch(group, opts, headers)
        results = poll_batch(batch_id, headers)
        all_results.extend(results)

    print("\nResults:")
    for f in all_results:
        flag = "OK " if f["state"] == "done" else "ERR"
        print(f"  [{flag}] {f.get('data_id') or f.get('file_name')}  "
              f"state={f['state']}  {f.get('err_msg', '')}")

    print("\nDownloading...")
    done_dirs = []
    for f in all_results:
        d = fetch_result(f, out_dir)
        if d:
            done_dirs.append(d)
            print(f"  extracted -> {d}  ({len(os.listdir(d))} files)")

    if args.preview and done_dirs:
        md = done_dirs[0] / "full.md"
        if md.exists():
            text = md.read_text(encoding="utf-8")
            print(f"\n--- {done_dirs[0].name}/full.md  ({len(text):,} chars) ---\n")
            print(text[: args.preview])

    n_ok = sum(1 for f in all_results if f["state"] == "done")
    n_err = len(all_results) - n_ok
    print(f"\nDone. {n_ok} succeeded, {n_err} failed. Output in: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
