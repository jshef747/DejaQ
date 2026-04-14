from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

_THEME = Theme(
    {
        "header.title": "bold bright_cyan",
        "header.sub": "dim cyan",
        "success": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
        "ns": "dim cyan",
        "col.header": "bold bright_white on grey23",
    }
)

console = Console(theme=_THEME)

_VERSION = "0.1.0"


def print_header() -> None:
    title = Text()
    title.append("Deja", style="bold bright_cyan")
    title.append("Q", style="bold bright_magenta")
    title.append(f"  Admin CLI  ", style="bold white")
    title.append(f"v{_VERSION}", style="dim white")

    subtitle = Text("Orgs · Departments · Cache Namespaces", style="dim cyan")

    content = Text()
    content.append_text(title)
    content.append("\n")
    content.append_text(subtitle)

    console.print(
        Panel(content, border_style="bright_cyan", padding=(0, 2)),
        highlight=False,
    )
    console.print()


def print_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    table = Table(
        title=title,
        title_style="bold bright_white",
        header_style="col.header",
        border_style="grey50",
        show_lines=False,
        expand=False,
    )
    for i, col in enumerate(columns):
        # Cache namespace column gets dim cyan style
        style = "ns" if "namespace" in col.lower() or "cache" in col.lower() else None
        table.add_column(col, style=style, no_wrap=True)

    for idx, row in enumerate(rows):
        table.add_row(*row, style="on grey7" if idx % 2 == 0 else "")

    if rows:
        console.print(table)
    else:
        console.print(
            Panel(
                f"[dim]No {title.lower()} found.[/dim]",
                border_style="dim",
                padding=(0, 2),
            )
        )


def print_success(msg: str) -> None:
    console.print(f"[success]✓[/success] {msg}")


def print_error(msg: str) -> None:
    console.print(f"[error]✗[/error] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[warning]⚠[/warning]  {msg}")
