from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Department:
    slug: str
    label: str


@dataclass(frozen=True)
class LoadCase:
    index: int
    department: str | None
    prompt: str
    expected: str  # hit | miss


async def fetch_departments(client: httpx.AsyncClient, base_url: str, api_key: str) -> list[Department]:
    response = await client.get(
        f"{base_url}/departments",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    response.raise_for_status()
    payload = response.json()
    return [Department(slug=item["slug"], label=item["label"]) for item in payload]


async def send_chat_request(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    case: LoadCase,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if case.department:
        headers["X-DejaQ-Department"] = case.department

    started = time.perf_counter()
    response = await client.post(
        f"{base_url}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": case.prompt}],
        },
    )
    elapsed = time.perf_counter() - started
    model_used = response.headers.get("x-dejaq-model-used", "unknown")

    body_preview = ""
    try:
        body = response.json()
        body_preview = body["choices"][0]["message"]["content"][:80]
    except Exception:
        body_preview = response.text[:80]

    return {
        "index": case.index,
        "department": case.department or "(org-default)",
        "expected": case.expected,
        "status_code": response.status_code,
        "model_used": model_used,
        "elapsed_seconds": elapsed,
        "body_preview": body_preview,
    }


def build_cases(departments: list[Department], concurrency: int) -> tuple[list[tuple[str | None, str]], list[LoadCase]]:
    if not departments:
        dept_cycle: list[str | None] = [None]
    else:
        dept_cycle = [dept.slug for dept in departments]

    seed_cases: list[tuple[str | None, str]] = []
    load_cases: list[LoadCase] = []

    hit_count = concurrency // 2
    miss_count = concurrency - hit_count

    for idx in range(hit_count):
        department = dept_cycle[idx % len(dept_cycle)]
        prompt = f"Shared cacheable question #{idx % max(1, len(dept_cycle))}: What is the capital of France?"
        seed_cases.append((department, prompt))
        load_cases.append(
            LoadCase(
                index=idx + 1,
                department=department,
                prompt=prompt,
                expected="hit",
            )
        )

    for idx in range(miss_count):
        department = dept_cycle[(idx + hit_count) % len(dept_cycle)]
        prompt = (
            f"Unique miss question {idx + 1}: explain the meaning of request id "
            f"{time.time_ns()}-{idx} in one sentence."
        )
        load_cases.append(
            LoadCase(
                index=hit_count + idx + 1,
                department=department,
                prompt=prompt,
                expected="miss",
            )
        )

    return seed_cases, load_cases


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fire 10 concurrent chat requests with mixed cache hits and misses across departments."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--department-count", type=int, default=3)
    parser.add_argument(
        "--seed-wait-seconds",
        type=float,
        default=5.0,
        help="Wait after seeding hit prompts so background cache store can finish.",
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=120.0) as client:
        departments = await fetch_departments(client, args.base_url, args.api_key)
        selected_departments = departments[: args.department_count]
        seed_cases, load_cases = build_cases(selected_departments, args.concurrency)

        print("Selected departments:")
        if selected_departments:
            for dept in selected_departments:
                print(f"  - {dept.slug} ({dept.label})")
        else:
            print("  - (org default only)")

        print("")
        print(f"Seeding {len(seed_cases)} cache-hit prompts...")
        for department, prompt in seed_cases:
            await send_chat_request(
                client=client,
                base_url=args.base_url,
                api_key=args.api_key,
                model=args.model,
                case=LoadCase(index=0, department=department, prompt=prompt, expected="seed"),
            )

        print(f"Waiting {args.seed_wait_seconds:.1f}s for background store...")
        await asyncio.sleep(args.seed_wait_seconds)

        print("")
        print(f"Launching {len(load_cases)} concurrent requests...")
        started = time.perf_counter()
        results = await asyncio.gather(
            *[
                send_chat_request(
                    client=client,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    model=args.model,
                    case=case,
                )
                for case in load_cases
            ]
        )
        total_elapsed = time.perf_counter() - started

    print("")
    print("Results:")
    hit_matches = 0
    miss_matches = 0
    for result in sorted(results, key=lambda item: item["index"]):
        expected = result["expected"]
        model_used = result["model_used"]
        if expected == "hit" and model_used == "cache":
            hit_matches += 1
        if expected == "miss" and model_used != "cache":
            miss_matches += 1
        print(
            f"  [{result['index']:02d}] dept={result['department']:<14} "
            f"expected={expected:<4} status={result['status_code']} "
            f"model_used={model_used:<10} latency={result['elapsed_seconds']:.2f}s"
        )

    print("")
    print(f"Wall clock total: {total_elapsed:.2f}s")
    print(f"Expected-hit requests served from cache: {hit_matches}/{len([c for c in load_cases if c.expected == 'hit'])}")
    print(f"Expected-miss requests served non-cache: {miss_matches}/{len([c for c in load_cases if c.expected == 'miss'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
