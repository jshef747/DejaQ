import sys

import click
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from app.db import dept_repo, org_repo
from app.db import api_key_repo
from app.db.session import get_session
from cli.ui import console, print_error, print_header, print_success, print_table, print_warning
from cli.stats import run as _run_stats


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


# ---------------------------------------------------------------------------
# key commands
# ---------------------------------------------------------------------------

@cli.group()
def key() -> None:
    """Manage org API keys."""


@key.command("generate")
@click.option("--org", "org_slug", required=True, help="Org slug to generate a key for.")
@click.option("--force", is_flag=True, default=False, help="Revoke existing active key and generate a new one.")
def key_generate(org_slug: str, force: bool) -> None:
    """Generate an API key for an org."""
    with get_session() as session:
        org_data = org_repo.get_org_by_slug(session, org_slug)
        if org_data is None:
            print_error(f"Organization '{org_slug}' not found.")
            sys.exit(1)

        existing = api_key_repo.get_active_key_for_org(session, org_data.id)
        if existing and not force:
            print_error(
                f"Organization '{org_slug}' already has an active key (id={existing.id}). "
                "Use --force to revoke it and generate a new one."
            )
            sys.exit(1)

        if existing and force:
            api_key_repo.revoke_key(session, existing.id)
            print_warning(f"Revoked existing key id={existing.id}.")

        new_key = api_key_repo.create_key(session, org_data.id)
        key_id = new_key.id
        key_token = new_key.token
        key_created_at = new_key.created_at

    content = Text()
    content.append("  id           ", style="dim")
    content.append(f"{key_id}\n", style="bright_white")
    content.append("  org          ", style="dim")
    content.append(f"{org_slug}\n", style="bright_white")
    content.append("  token        ", style="dim")
    content.append(f"{key_token}\n", style="bold bright_cyan")
    content.append("  created_at   ", style="dim")
    content.append(f"{key_created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="bright_white")

    console.print(Panel(content, title="[green]API key generated[/green]", border_style="green", padding=(0, 2)))


@key.command("list")
@click.option("--org", "org_slug", required=True, help="Org slug to list keys for.")
def key_list(org_slug: str) -> None:
    """List all API keys for an org."""
    with get_session() as session:
        org_data = org_repo.get_org_by_slug(session, org_slug)
        if org_data is None:
            print_error(f"Organization '{org_slug}' not found.")
            sys.exit(1)
        raw_keys = api_key_repo.list_keys_for_org(session, org_data.id)
        # Snapshot values before session closes to avoid DetachedInstanceError
        keys = [
            (k.id, k.token, k.created_at, k.revoked_at)
            for k in raw_keys
        ]

    if not keys:
        console.print(f"[dim]No API keys found for org '{org_slug}'.[/dim]")
        return

    print_table(
        f"API Keys — {org_slug}",
        ["ID", "Token", "Created", "Revoked"],
        [
            [
                str(kid),
                token[:12] + "...",
                created_at.strftime("%Y-%m-%d %H:%M"),
                revoked_at.strftime("%Y-%m-%d %H:%M") if revoked_at else "—",
            ]
            for kid, token, created_at, revoked_at in keys
        ],
    )


@key.command("revoke")
@click.option("--id", "key_id", required=True, type=int, help="ID of the key to revoke.")
def key_revoke(key_id: int) -> None:
    """Revoke an API key by its ID."""
    with get_session() as session:
        from app.db.models.api_key import ApiKey as ApiKeyModel
        existing = session.query(ApiKeyModel).filter(ApiKeyModel.id == key_id).first()
        if existing is None:
            print_error(f"Key id={key_id} not found.")
            sys.exit(1)
        already_revoked = existing.revoked_at is not None
        result = api_key_repo.revoke_key(session, key_id)
        # Snapshot before session closes
        result_id = result.id
        result_revoked_at = result.revoked_at

    if already_revoked:
        print_warning(f"Key id={key_id} was already revoked at {result_revoked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}.")
        return

    print_success(
        f"Key id={result_id} revoked at {result_revoked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}."
    )


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

@cli.command("stats")
def stats_cmd() -> None:
    """Show usage stats: cache hit rates, latency, and model routing per department."""
    _run_stats()
