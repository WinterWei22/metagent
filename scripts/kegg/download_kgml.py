"""Download KGML XML for the required KEGG pathway IDs.

Reads ``data/kegg/required_pathway_ids.txt`` (output of
``extract_required_pathways.py``) and pulls each pathway's KGML from
KEGG REST. Strictly idempotent — re-running skips any pathway whose
KGML already exists locally with non-zero size.

Rate limit: 1 request / second by default (KEGG fair-use policy).
Failures get one exponential-backoff retry; persistent failures land
in the audit log so the caller can decide whether to ship a partial
graph or block.

Audit log (``data/kegg/download_audit.json``) records, per pathway:

    {
      "kegg_id":   "hsa00270",
      "url":       "https://rest.kegg.jp/get/hsa00270/kgml",
      "status":    "ok" | "skipped" | "failed",
      "http_code": 200,
      "size":      75547,
      "fetched":   "2026-05-03T01:05:32Z",
      "attempts":  1,
      "error":     null
    }

The audit lets D7 cite the access date + per-file MD5 in the report's
provenance section without recomputing.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

KEGG_BASE_URL = "https://rest.kegg.jp/get"
USER_AGENT = "metagent-verifier-kegg/1.0 (+research; offline-cache)"


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 — non-security checksum
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_one(kegg_id: str, url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — known KEGG host
        code = getattr(resp, "status", 200)
        body = resp.read()
    return code, body


def _download_with_retry(
    kegg_id: str,
    out_path: Path,
    *,
    timeout: float,
    backoff: float,
) -> dict:
    url = f"{KEGG_BASE_URL}/{kegg_id}/kgml"
    record = {
        "kegg_id": kegg_id,
        "url": url,
        "status": "failed",
        "http_code": None,
        "size": None,
        "fetched": None,
        "attempts": 0,
        "error": None,
        "md5": None,
    }
    last_err: str | None = None
    for attempt in (1, 2):
        record["attempts"] = attempt
        try:
            code, body = _fetch_one(kegg_id, url, timeout=timeout)
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}: {e.reason}"
            record["http_code"] = e.code
            if e.code == 404:
                # 404 won't recover from retry; stop now.
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
        else:
            if not body or len(body) < 200:
                last_err = f"body too small ({len(body) if body else 0} bytes); KGML expected ≥ 200B"
                record["http_code"] = code
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(body)
                record.update(
                    status="ok",
                    http_code=code,
                    size=len(body),
                    fetched=_now_iso(),
                    md5=_md5(out_path),
                    error=None,
                )
                return record
        if attempt == 1:
            time.sleep(backoff)
    record["error"] = last_err
    return record


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--pathway-list",
        default="data/kegg/required_pathway_ids.txt",
        help="One hsaNNNNN ID per line (output of extract_required_pathways.py)",
    )
    p.add_argument("--output-dir", default="data/kegg/kgml")
    p.add_argument(
        "--audit",
        default="data/kegg/download_audit.json",
        help="Per-pathway audit log (status, size, md5, fetched_at)",
    )
    p.add_argument(
        "--request-interval",
        type=float,
        default=1.0,
        help="Seconds between requests (KEGG fair-use)",
    )
    p.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout (s)")
    p.add_argument("--backoff", type=float, default=2.0, help="Retry backoff before 2nd attempt")
    p.add_argument("--limit", type=int, default=None, help="Cap downloads (testing)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    pathway_path = Path(args.pathway_list)
    if not pathway_path.is_file():
        sys.stderr.write(f"ERROR: pathway list not found: {pathway_path}\n")
        return 2

    ids = [line.strip() for line in pathway_path.read_text().splitlines() if line.strip()]
    if args.limit is not None:
        ids = ids[: args.limit]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resume audit if present so successive runs can extend it.
    audit_path = Path(args.audit)
    audit: dict[str, dict] = {}
    if audit_path.is_file():
        try:
            audit = {r["kegg_id"]: r for r in json.loads(audit_path.read_text())}
        except (json.JSONDecodeError, KeyError):
            audit = {}

    n_ok = n_skip = n_fail = 0
    t0 = time.perf_counter()

    for i, kid in enumerate(ids):
        out_path = out_dir / f"{kid}.xml"
        if out_path.is_file() and out_path.stat().st_size >= 200:
            # already have it — record skip and continue
            audit[kid] = {
                "kegg_id": kid,
                "url": f"{KEGG_BASE_URL}/{kid}/kgml",
                "status": "skipped",
                "http_code": None,
                "size": out_path.stat().st_size,
                "fetched": audit.get(kid, {}).get("fetched"),
                "attempts": 0,
                "error": None,
                "md5": _md5(out_path),
            }
            n_skip += 1
            continue

        record = _download_with_retry(
            kid, out_path, timeout=args.timeout, backoff=args.backoff
        )
        audit[kid] = record
        if record["status"] == "ok":
            n_ok += 1
            logger.info(
                "[%d/%d] %s ok %d B (md5=%s)",
                i + 1, len(ids), kid, record["size"], record["md5"][:8],
            )
        else:
            n_fail += 1
            logger.warning(
                "[%d/%d] %s FAILED: %s (http=%s, attempts=%d)",
                i + 1, len(ids), kid, record["error"], record["http_code"], record["attempts"],
            )
        # Throttle between live downloads (skip after a 'skipped' since
        # nothing was sent).
        time.sleep(args.request_interval)

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(sorted(audit.values(), key=lambda r: r["kegg_id"]), indent=2))

    elapsed = time.perf_counter() - t0
    print()
    print(f"Downloaded {n_ok} new, skipped {n_skip}, failed {n_fail}, total ids={len(ids)}")
    print(f"Wall time: {elapsed:.1f}s; audit: {audit_path}")
    if n_fail:
        print("\nFailed IDs:")
        for r in audit.values():
            if r["status"] == "failed":
                print(f"  - {r['kegg_id']:<10} {r.get('error')}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
