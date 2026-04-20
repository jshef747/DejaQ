"""
Standalone stats viewer: uv run python -m cli.stats
"""
import os
import sqlite3
import sys

from rich.console import Console
from rich.table import Table
from rich import box

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

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    rows = cur.execute("""
        SELECT
            org,
            department,
            COUNT(*)                                          AS total,
            SUM(cache_hit)                                   AS hits,
            COUNT(*) - SUM(cache_hit)                        AS misses,
            AVG(latency_ms)                                  AS avg_lat,
            SUM(CASE WHEN difficulty = 'easy' THEN 1 ELSE 0 END) AS easy,
            SUM(CASE WHEN difficulty = 'hard' THEN 1 ELSE 0 END) AS hard,
            GROUP_CONCAT(DISTINCT model_used)                AS models
        FROM requests
        GROUP BY org, department
        ORDER BY org, department
    """).fetchall()

    if not rows:
        Console().print("[dim]No requests recorded yet.[/dim]")
        con.close()
        return

    totals = cur.execute("""
        SELECT
            COUNT(*)                                          AS total,
            SUM(cache_hit)                                   AS hits,
            COUNT(*) - SUM(cache_hit)                        AS misses,
            AVG(latency_ms)                                  AS avg_lat,
            SUM(CASE WHEN difficulty = 'easy' THEN 1 ELSE 0 END) AS easy,
            SUM(CASE WHEN difficulty = 'hard' THEN 1 ELSE 0 END) AS hard,
            GROUP_CONCAT(DISTINCT model_used)                AS models
        FROM requests
    """).fetchone()
    con.close()

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

    for org, dept, total, hits, misses, avg_lat, easy, hard, models in rows:
        hits = hits or 0
        easy = easy or 0
        hard = hard or 0
        hit_rate = hits / total if total else 0
        style = _style(hit_rate)
        tokens_saved = hits * _TOKENS_PER_HIT
        model_list = ", ".join(m for m in (models or "").split(",") if m) or "—"
        table.add_row(
            org,
            dept,
            str(total),
            _fmt_pct(hits, total),
            _fmt_latency(avg_lat),
            f"{tokens_saved:,}",
            str(easy),
            str(hard),
            model_list,
            style=style,
        )

    # Total row
    if totals:
        t_total, t_hits, t_misses, t_avg_lat, t_easy, t_hard, t_models = totals
        t_hits = t_hits or 0
        t_easy = t_easy or 0
        t_hard = t_hard or 0
        t_hit_rate = t_hits / t_total if t_total else 0
        t_style = _style(t_hit_rate)
        t_tokens = t_hits * _TOKENS_PER_HIT
        t_model_list = ", ".join(m for m in (t_models or "").split(",") if m) or "—"
        table.add_section()
        table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            f"[bold]{t_total}[/bold]",
            f"[bold]{_fmt_pct(t_hits, t_total)}[/bold]",
            f"[bold]{_fmt_latency(t_avg_lat)}[/bold]",
            f"[bold]{t_tokens:,}[/bold]",
            f"[bold]{t_easy}[/bold]",
            f"[bold]{t_hard}[/bold]",
            f"[bold]{t_model_list}[/bold]",
            style=t_style,
        )

    Console().print(table)


if __name__ == "__main__":
    run()
