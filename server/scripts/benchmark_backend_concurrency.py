from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from app.services.model_backends import CompletionRequest, InProcessBackend, OllamaBackend


def _build_request(model_name: str, prompt: str, max_tokens: int, temperature: float) -> CompletionRequest:
    return CompletionRequest(
        model_name=model_name,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def _run_once(backend, request: CompletionRequest, concurrency: int) -> float:
    started = time.perf_counter()
    await asyncio.gather(*(backend.complete(request) for _ in range(concurrency)))
    return time.perf_counter() - started


async def _benchmark(args: argparse.Namespace) -> int:
    if args.backend == "in_process":
        backend = InProcessBackend()
    else:
        backend = OllamaBackend(
            base_url=args.ollama_url,
            timeout_seconds=args.timeout,
        )

    request = _build_request(
        model_name=args.model,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    if args.warmup > 0:
        for _ in range(args.warmup):
            await backend.complete(request)

    single_runs = [await _run_once(backend, request, 1) for _ in range(args.runs)]
    concurrent_runs = [await _run_once(backend, request, args.concurrency) for _ in range(args.runs)]

    single_avg = statistics.mean(single_runs)
    concurrent_avg = statistics.mean(concurrent_runs)
    serial_estimate = single_avg * args.concurrency
    ratio_vs_single = concurrent_avg / single_avg if single_avg else float("inf")
    ratio_vs_serial = concurrent_avg / serial_estimate if serial_estimate else float("inf")
    passed = ratio_vs_serial < args.max_serial_ratio

    print(f"backend={args.backend}")
    print(f"model={args.model}")
    print(f"prompt={args.prompt!r}")
    print(f"concurrency={args.concurrency}")
    print(f"runs={args.runs}")
    print(f"single_avg_seconds={single_avg:.3f}")
    print(f"concurrent_avg_seconds={concurrent_avg:.3f}")
    print(f"serial_estimate_seconds={serial_estimate:.3f}")
    print(f"ratio_vs_single={ratio_vs_single:.2f}x")
    print(f"ratio_vs_serial={ratio_vs_serial:.2f}")
    print(f"threshold_ratio_vs_serial={args.max_serial_ratio:.2f}")
    print(f"result={'PASS' if passed else 'FAIL'}")

    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark backend concurrency by comparing one request vs N concurrent requests."
    )
    parser.add_argument("--backend", choices=("in_process", "ollama"), required=True)
    parser.add_argument("--model", required=True, help="Logical model name, e.g. qwen_0_5b or gemma_local")
    parser.add_argument("--prompt", default="What is the capital of France?")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--max-serial-ratio",
        type=float,
        default=0.9,
        help="Fail if concurrent wall-clock is this close to naive serial time.",
    )
    args = parser.parse_args()
    return asyncio.run(_benchmark(args))


if __name__ == "__main__":
    raise SystemExit(main())
