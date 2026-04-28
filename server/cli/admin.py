import sys

import click
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from app.dependencies.management_auth import ManagementAuthContext
from app.services import admin_service
from cli.ui import console, print_error, print_header, print_success, print_table, print_warning
from cli.stats import run as _run_stats

_SYSTEM_CTX = ManagementAuthContext.system()


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
            result = admin_service.create_org(name, ctx=_SYSTEM_CTX)
        except admin_service.DuplicateSlug as e:
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
    orgs = admin_service.list_orgs(ctx=_SYSTEM_CTX)

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
    try:
        depts = admin_service.list_departments(org_slug=slug, ctx=_SYSTEM_CTX)
    except admin_service.OrgNotFound:
        print_error(f"Organization '{slug}' not found.")
        sys.exit(1)

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
        result = admin_service.delete_org(slug, ctx=_SYSTEM_CTX)

    print_success(
        f"Organization [bold]{slug}[/bold] deleted"
        + (f" (and {result.departments_removed} department(s) removed)." if result.departments_removed else ".")
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
            result = admin_service.create_department(org_slug, name, ctx=_SYSTEM_CTX)
        except (admin_service.OrgNotFound, admin_service.DuplicateSlug) as e:
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
        depts = admin_service.list_departments(org_slug=org_slug, ctx=_SYSTEM_CTX)
    except admin_service.OrgNotFound as e:
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
                    d.org_slug,
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
    try:
        dept_data = next(
            (dept for dept in admin_service.list_departments(org_slug=org_slug, ctx=_SYSTEM_CTX) if dept.slug == slug),
            None,
        )
    except admin_service.OrgNotFound:
        dept_data = None
    if dept_data is None:
        print_error(f"Department '{slug}' not found under org '{org_slug}'.")
        sys.exit(1)

    if not Confirm.ask(f"[yellow]Delete department [bold]{slug}[/bold] (namespace: [cyan]{dept_data.cache_namespace}[/cyan])?[/yellow]"):
        print_warning("Aborted.")
        sys.exit(0)

    with console.status("[cyan]Deleting…[/cyan]", spinner="dots"):
        deleted = admin_service.delete_department(org_slug, slug, ctx=_SYSTEM_CTX)

    print_success(
        f"Department [bold]{slug}[/bold] deleted. "
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
    try:
        new_key = admin_service.generate_key(org_slug, force=force, ctx=_SYSTEM_CTX)
    except admin_service.OrgNotFound:
        print_error(f"Organization '{org_slug}' not found.")
        sys.exit(1)
    except admin_service.ActiveKeyExists as e:
        print_error(
            f"Organization '{org_slug}' already has an active key (id={e.key_id}). "
            "Use --force to revoke it and generate a new one."
        )
        sys.exit(1)

    content = Text()
    content.append("  id           ", style="dim")
    content.append(f"{new_key.id}\n", style="bright_white")
    content.append("  org          ", style="dim")
    content.append(f"{org_slug}\n", style="bright_white")
    content.append("  token        ", style="dim")
    content.append(f"{new_key.token}\n", style="bold bright_cyan")
    content.append("  created_at   ", style="dim")
    content.append(f"{new_key.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="bright_white")

    console.print(Panel(content, title="[green]API key generated[/green]", border_style="green", padding=(0, 2)))


@key.command("list")
@click.option("--org", "org_slug", required=True, help="Org slug to list keys for.")
def key_list(org_slug: str) -> None:
    """List all API keys for an org."""
    try:
        keys = admin_service.list_keys(org_slug, ctx=_SYSTEM_CTX)
    except admin_service.OrgNotFound:
        print_error(f"Organization '{org_slug}' not found.")
        sys.exit(1)

    if not keys:
        console.print(f"[dim]No API keys found for org '{org_slug}'.[/dim]")
        return

    print_table(
        f"API Keys — {org_slug}",
        ["ID", "Token", "Created", "Revoked"],
        [
            [
                str(k.id),
                k.token_prefix,
                k.created_at.strftime("%Y-%m-%d %H:%M"),
                k.revoked_at.strftime("%Y-%m-%d %H:%M") if k.revoked_at else "—",
            ]
            for k in keys
        ],
    )


@key.command("revoke")
@click.option("--id", "key_id", required=True, type=int, help="ID of the key to revoke.")
def key_revoke(key_id: int) -> None:
    """Revoke an API key by its ID."""
    try:
        result = admin_service.revoke_key(key_id, ctx=_SYSTEM_CTX)
    except admin_service.KeyNotFound:
        print_error(f"Key id={key_id} not found.")
        sys.exit(1)

    if result.already_revoked:
        print_warning(f"Key id={key_id} was already revoked at {result.revoked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}.")
        return

    print_success(
        f"Key id={result.id} revoked at {result.revoked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}."
    )


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

@cli.command("stats")
def stats_cmd() -> None:
    """Show usage stats: cache hit rates, latency, and model routing per department."""
    _run_stats()


# ---------------------------------------------------------------------------
# seed commands
# ---------------------------------------------------------------------------

@cli.group()
def seed() -> None:
    """Seed commands for demo and setup data."""


@seed.command("demo")
@click.option(
    "--provider-key-stdin",
    "provider_key_stdin",
    metavar="PROVIDER",
    default=None,
    help="Read a provider API key from stdin and seed it for the demo org.",
)
def seed_demo_cmd(provider_key_stdin: str | None) -> None:
    """Idempotently seed demo org, departments, user, membership, and sample stats."""
    from cli.seed import seed_demo

    provider_key = None
    if provider_key_stdin:
        provider_key = sys.stdin.read().strip()
        if not provider_key:
            print_error("--provider-key-stdin was provided, but stdin was empty.")
            sys.exit(1)

    with console.status("[cyan]Seeding demo workspace…[/cyan]", spinner="dots"):
        try:
            summary = seed_demo(provider_key_provider=provider_key_stdin, provider_key=provider_key)
        except ValueError as exc:
            print_error(str(exc))
            sys.exit(1)

    console.print(f"[green]Demo seed complete.[/green]")
    console.print(f"  org:         {summary['org']}")
    console.print(f"  departments: {', '.join(summary['departments'])}")
    console.print(f"  user:        {summary['user']}")
    console.print(f"  membership:  {summary['membership']}")
    console.print(f"  stats rows inserted: {summary['stats_rows']}")
    if summary.get("credential") == "skipped_missing_encryption_key":
        print_warning(
            "Provider credential supplied, but DEJAQ_CREDENTIAL_ENCRYPTION_KEY is not set; skipped credential upsert."
        )
    elif summary.get("credential") != "not_supplied":
        console.print(f"  provider credential: {summary['credential']}")
    console.print("")
    console.print(f"  [dim]Demo credentials:[/dim] demo@dejaq.local / demo1234")
