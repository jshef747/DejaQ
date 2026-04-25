"""
Standalone stats viewer: uv run python -m cli.stats
"""
import os
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

from app.services import stats_service

_TOKENS_PER_HIT = 150


def _style(hit_rate: float) -> str:
    return "green" if hit_rate >= 0.5 else "yellow"


def _fmt_pct(hits: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{hits / total * 100:.1f}%"


def _fmt_latency(avg: float | None) -> str:
    if avg is None:
        return "—"
    return f"{avg:.0f} ms"


def run() -> None:
    db_path = os.getenv("DEJAQ_STATS_DB", "dejaq_stats.db")

    if not os.path.exists(db_path):
        Console().print(f"[red]Stats DB not found:[/red] {db_path}\nStart the server and send some requests first.")
        sys.exit(1)

    org_report = stats_service.org_stats()
    department_rows = []
    for org in org_report.items:
        department_rows.extend(stats_service.department_stats(org.org).items)

    if not department_rows:
        Console().print("[dim]No requests recorded yet.[/dim]")
        return

    table = Table(
        title="[bold]DejaQ Usage Stats[/bold]",
        box=box.ROUNDED,
        show_footer=False,
        header_style="bold cyan",
    )
    table.add_column("Org", style="dim")
    table.add_column("Department")
    table.add_column("Requests", justify="right")
    table.add_column("Hit Rate", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Est. Tokens Saved", justify="right")
    table.add_column("Easy Misses", justify="right")
    table.add_column("Hard Misses", justify="right")
    table.add_column("Models Used")

    for row in department_rows:
        style = _style(row.hit_rate)
        model_list = ", ".join(row.models_used) or "—"
        table.add_row(
            row.org,
            row.department,
            str(row.requests),
            _fmt_pct(row.hits, row.requests),
            _fmt_latency(row.avg_latency_ms),
            f"{row.est_tokens_saved:,}",
            str(row.easy_count),
            str(row.hard_count),
            model_list,
            style=style,
        )

    # Total row
    if org_report.total.requests:
        total = org_report.total
        t_style = _style(total.hit_rate)
        t_model_list = ", ".join(total.models_used) or "—"
        table.add_section()
        table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            f"[bold]{total.requests}[/bold]",
            f"[bold]{_fmt_pct(total.hits, total.requests)}[/bold]",
            f"[bold]{_fmt_latency(total.avg_latency_ms)}[/bold]",
            f"[bold]{total.est_tokens_saved:,}[/bold]",
            f"[bold]{total.easy_count}[/bold]",
            f"[bold]{total.hard_count}[/bold]",
            f"[bold]{t_model_list}[/bold]",
            style=t_style,
        )

    console = Console()
    console.print(table)
    console.print()
    _print_cache_health(console, db_path)


def _print_cache_health(console: Console, db_path: str) -> None:
    """Print a Cache Health panel showing score distribution across cached entries."""
    try:
        import chromadb
        from app.config import CHROMA_HOST, CHROMA_PORT, EVICTION_FLOOR
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collections = client.list_collections()
    except Exception as exc:
        console.print(f"[dim]Cache Health unavailable: {exc}[/dim]")
        return

    total = 0
    positive = 0
    neutral = 0
    negative = 0
    below_floor = 0

    for col in collections:
        try:
            collection = client.get_collection(col.name)
            results = collection.get(include=["metadatas"])
            for meta in (results["metadatas"] or []):
                score = float(meta.get("score", 0.0))
                total += 1
                if score > 0:
                    positive += 1
                elif score == 0:
                    neutral += 1
                else:
                    negative += 1
                if score < EVICTION_FLOOR:
                    below_floor += 1
        except Exception:
            pass

    lines = [
        f"[bold]Total entries:[/bold] {total}",
        f"[green]Score > 0:[/green]   {positive}",
        f"[dim]Score = 0:[/dim]   {neutral}",
        f"[yellow]Score < 0:[/yellow]  {negative}",
        f"[red]Below floor:[/red] {below_floor}  [dim](floor={EVICTION_FLOOR})[/dim]",
    ]
    console.print(Panel("\n".join(lines), title="[bold]Cache Health[/bold]", expand=False))


if __name__ == "__main__":
    run()
