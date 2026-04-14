import sys

import click
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from app.db import dept_repo, org_repo
from app.db.session import get_session
from cli.ui import console, print_error, print_header, print_success, print_table, print_warning


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """DejaQ Admin — manage orgs, departments, and cache namespaces."""
    print_header()


# ---------------------------------------------------------------------------
# org commands
# ---------------------------------------------------------------------------

@cli.group()
def org() -> None:
    """Manage organizations."""


@org.command("create")
@click.option("--name", required=True, help="Display name for the organization.")
def org_create(name: str) -> None:
    """Create a new organization."""
    with console.status("[cyan]Creating organization…[/cyan]", spinner="dots"):
        try:
            with get_session() as session:
                result = org_repo.create_org(session, name)
        except ValueError as e:
            print_error(str(e))
            sys.exit(1)

    content = Text()
    content.append(f"  id    ", style="dim")
    content.append(f"{result.id}\n", style="bright_white")
    content.append(f"  name  ", style="dim")
    content.append(f"{result.name}\n", style="bright_white")
    content.append(f"  slug  ", style="dim")
    content.append(f"{result.slug}", style="bright_cyan")

    console.print(Panel(content, title="[green]Organization created[/green]", border_style="green", padding=(0, 2)))


@org.command("list")
def org_list() -> None:
    """List all organizations."""
    with get_session() as session:
        orgs = org_repo.list_orgs(session)

    print_table(
        "Organizations",
        ["ID", "Name", "Slug", "Created"],
        [
            [str(o.id), o.name, o.slug, o.created_at.strftime("%Y-%m-%d %H:%M")]
            for o in orgs
        ],
    )


@org.command("delete")
@click.option("--slug", required=True, help="Slug of the organization to delete.")
def org_delete(slug: str) -> None:
    """Delete an organization and all its departments."""
    # Preview cascade
    with get_session() as session:
        org_data = org_repo.get_org_by_slug(session, slug)
        if org_data is None:
            print_error(f"Organization '{slug}' not found.")
            sys.exit(1)
        depts = dept_repo.list_depts(session, org_slug=slug)

    if depts:
        dept_list = "\n".join(f"  • [dim cyan]{d.slug}[/dim cyan]" for d in depts)
        console.print(
            Panel(
                f"[yellow]Deleting org [bold]{slug}[/bold] will also remove {len(depts)} department(s):[/yellow]\n{dept_list}",
                title="[yellow]Cascade warning[/yellow]",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        if not Confirm.ask("[yellow]Proceed?[/yellow]"):
            print_warning("Aborted.")
            sys.exit(0)

    with console.status("[cyan]Deleting…[/cyan]", spinner="dots"):
        with get_session() as session:
            dept_count = org_repo.delete_org(session, slug)

    print_success(
        f"Organization [bold]{slug}[/bold] deleted"
        + (f" (and {dept_count} department(s) removed)." if dept_count else ".")
    )


# ---------------------------------------------------------------------------
# dept commands
# ---------------------------------------------------------------------------

@cli.group()
def dept() -> None:
    """Manage departments."""


@dept.command("create")
@click.option("--org", "org_slug", required=True, help="Parent org slug.")
@click.option("--name", required=True, help="Display name for the department.")
def dept_create(org_slug: str, name: str) -> None:
    """Create a new department under an org."""
    with console.status("[cyan]Creating department…[/cyan]", spinner="dots"):
        try:
            with get_session() as session:
                result = dept_repo.create_dept(session, org_slug, name)
        except ValueError as e:
            print_error(str(e))
            sys.exit(1)

    content = Text()
    content.append(f"  id               ", style="dim")
    content.append(f"{result.id}\n", style="bright_white")
    content.append(f"  name             ", style="dim")
    content.append(f"{result.name}\n", style="bright_white")
    content.append(f"  slug             ", style="dim")
    content.append(f"{result.slug}\n", style="bright_white")
    content.append(f"  cache_namespace  ", style="dim")
    content.append(f"{result.cache_namespace}", style="bold bright_cyan")

    console.print(Panel(content, title="[green]Department created[/green]", border_style="green", padding=(0, 2)))


@dept.command("list")
@click.option("--org", "org_slug", default=None, help="Filter by org slug.")
def dept_list(org_slug: str | None) -> None:
    """List departments, optionally filtered by org."""
    try:
        with get_session() as session:
            depts = dept_repo.list_depts(session, org_slug=org_slug)
            # Need org slug for each dept when listing all
            if not org_slug:
                from app.db.models.org import Organization
                org_map = {
                    o.id: o.slug
                    for o in session.query(Organization).all()
                }
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    if org_slug:
        print_table(
            f"Departments — {org_slug}",
            ["ID", "Name", "Slug", "Cache Namespace", "Created"],
            [
                [
                    str(d.id),
                    d.name,
                    d.slug,
                    d.cache_namespace,
                    d.created_at.strftime("%Y-%m-%d %H:%M"),
                ]
                for d in depts
            ],
        )
    else:
        print_table(
            "All Departments",
            ["ID", "Org", "Name", "Slug", "Cache Namespace", "Created"],
            [
                [
                    str(d.id),
                    org_map.get(d.org_id, "?"),
                    d.name,
                    d.slug,
                    d.cache_namespace,
                    d.created_at.strftime("%Y-%m-%d %H:%M"),
                ]
                for d in depts
            ],
        )


@dept.command("delete")
@click.option("--org", "org_slug", required=True, help="Parent org slug.")
@click.option("--slug", required=True, help="Department slug to delete.")
def dept_delete(org_slug: str, slug: str) -> None:
    """Delete a department."""
    with get_session() as session:
        dept_data = dept_repo.get_dept(session, org_slug, slug)
        if dept_data is None:
            print_error(f"Department '{slug}' not found under org '{org_slug}'.")
            sys.exit(1)

    if not Confirm.ask(f"[yellow]Delete department [bold]{slug}[/bold] (namespace: [cyan]{dept_data.cache_namespace}[/cyan])?[/yellow]"):
        print_warning("Aborted.")
        sys.exit(0)

    with console.status("[cyan]Deleting…[/cyan]", spinner="dots"):
        with get_session() as session:
            deleted = dept_repo.delete_dept(session, org_slug, slug)

    print_success(
        f"Department [bold]{deleted.slug}[/bold] deleted. "
        f"Freed namespace: [cyan]{deleted.cache_namespace}[/cyan]"
    )
