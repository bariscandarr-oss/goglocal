from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://goglocal.app"
DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "test_queries.json"


@dataclass
class CaseResult:
    case_id: str
    query: str
    ok: bool
    reason: str
    top_names: list[str]


def _any_overlap(values: set[str], expected: list[str]) -> bool:
    if not expected:
        return True
    expected_set = set(expected)
    return bool(values.intersection(expected_set))


def _evaluate_case(response: dict[str, Any], case: dict[str, Any]) -> tuple[bool, str]:
    results = response.get("results", [])
    expect_empty = bool(case.get("expect_empty", False))
    if expect_empty:
        if not results:
            return True, "ok_empty"
        return False, "expected_empty_got_results"

    if not results:
        return False, "empty_results"

    top_k = int(case.get("top_k", 5))
    pool = results[:top_k]

    expected_areas = list(case.get("expect_any_areas", []))
    expected_categories = list(case.get("expect_any_categories", []))
    expected_tags = list(case.get("expect_any_tags", []))

    areas = {((x.get("place") or {}).get("area") or "").strip().lower() for x in pool}
    categories = {((x.get("place") or {}).get("category") or "").strip().lower() for x in pool}
    tags: set[str] = set()
    for item in pool:
        place = item.get("place") or {}
        for t in place.get("tags", []):
            if isinstance(t, str):
                tags.add(t.strip().lower())

    area_ok = _any_overlap(areas, [a.lower() for a in expected_areas])
    category_ok = _any_overlap(categories, [c.lower() for c in expected_categories])
    tag_ok = _any_overlap(tags, [t.lower() for t in expected_tags])

    if area_ok and category_ok and tag_ok:
        return True, "ok"

    reasons: list[str] = []
    if not area_ok:
        reasons.append("area_mismatch")
    if not category_ok:
        reasons.append("category_mismatch")
    if not tag_ok:
        reasons.append("tag_mismatch")
    return False, ",".join(reasons)


def run(base_url: str, dataset_path: Path, timeout_s: float, min_pass_rate: float) -> int:
    data = json.loads(dataset_path.read_text())
    if not isinstance(data, list):
        raise RuntimeError("Dataset must be a JSON list")

    client = httpx.Client(timeout=timeout_s)
    results: list[CaseResult] = []

    for case in data:
        case_id = str(case.get("id", "unknown"))
        query = str(case.get("query", "")).strip()
        payload = {"query": query, "max_results": int(case.get("top_k", 5))}
        try:
            resp = client.post(f"{base_url.rstrip('/')}/search", json=payload)
            resp.raise_for_status()
            body = resp.json()
            ok, reason = _evaluate_case(body, case)
            top_names = [((x.get("place") or {}).get("name") or "") for x in body.get("results", [])[:3]]
            results.append(CaseResult(case_id=case_id, query=query, ok=ok, reason=reason, top_names=top_names))
        except Exception as exc:
            results.append(CaseResult(case_id=case_id, query=query, ok=False, reason=f"request_error:{exc}", top_names=[]))

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    score = (passed / total * 100.0) if total else 0.0

    print(f"Quality Score: {score:.1f}% ({passed}/{total})")
    print("-" * 72)
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        print(f"[{status}] {r.case_id} | {r.query}")
        print(f"       reason: {r.reason}")
        if r.top_names:
            print(f"       top3: {', '.join(r.top_names)}")

    if score < min_pass_rate:
        print(f"\nGate: FAIL (score {score:.1f}% < min {min_pass_rate:.1f}%)")
        return 1
    print(f"\nGate: PASS (score {score:.1f}% >= min {min_pass_rate:.1f}%)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate search quality against a query dataset.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL (default: https://goglocal.app)")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to dataset json file")
    parser.add_argument("--timeout", type=float, default=25.0, help="Request timeout in seconds")
    parser.add_argument("--min-pass-rate", type=float, default=85.0, help="Minimum pass rate percentage for quality gate")
    args = parser.parse_args()

    return run(
        base_url=args.base_url,
        dataset_path=Path(args.dataset),
        timeout_s=args.timeout,
        min_pass_rate=args.min_pass_rate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
