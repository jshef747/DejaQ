import sys

import click
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from app.services import admin_service
from cli.ui import console, print_error, print_header, print_success, print_table, print_warning
from cli.stats import run as _run_stats


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """DejaQ Admin — manage workspaces, departments, and cache namespaces."""
    print_header()


# ---------------------------------------------------------------------------
# workspace commands
# ---------------------------------------------------------------------------

@cli.group()
def workspace() -> None:
    """Manage workspaces."""


# Keep legacy 'org' alias for one release to avoid breaking existing operator scripts.
@cli.group(hidden=True)
def org() -> None:
    """[Deprecated] Use 'workspace' instead."""


@workspace.command("create")
@click.option("--name", required=True, help="Display name for the workspace.")
def workspace_create(name: str) -> None:
    """Create a new workspace."""
    with console.status("[cyan]Creating workspace…[/cyan]", spinner="dots"):
        try:
            result = admin_service.create_workspace(name)
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

    console.print(Panel(content, title="[green]Workspace created[/green]", border_style="green", padding=(0, 2)))


@workspace.command("list")
def workspace_list() -> None:
    """List all workspaces."""
    workspaces = admin_service.list_workspaces()

    print_table(
        "Workspaces",
        ["ID", "Name", "Slug", "Created"],
        [
            [str(w.id), w.name, w.slug, w.created_at.strftime("%Y-%m-%d %H:%M")]
            for w in workspaces
        ],
    )


@workspace.command("delete")
@click.option("--slug", required=True, help="Slug of the workspace to delete.")
def workspace_delete(slug: str) -> None:
    """Delete a workspace and all its departments."""
    # Preview cascade
    try:
        depts = admin_service.list_departments(workspace_slug=slug)
    except admin_service.WorkspaceNotFound:
        print_error(f"Workspace '{slug}' not found.")
        sys.exit(1)

    if depts:
        dept_list = "\n".join(f"  • [dim cyan]{d.slug}[/dim cyan]" for d in depts)
        console.print(
            Panel(
                f"[yellow]Deleting workspace [bold]{slug}[/bold] will also remove {len(depts)} department(s):[/yellow]\n{dept_list}",
                title="[yellow]Cascade warning[/yellow]",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        if not Confirm.ask("[yellow]Proceed?[/yellow]"):
            print_warning("Aborted.")
            sys.exit(0)

    with console.status("[cyan]Deleting…[/cyan]", spinner="dots"):
        result = admin_service.delete_workspace(slug)

    print_success(
        f"Workspace [bold]{slug}[/bold] deleted"
        + (f" (and {result.departments_removed} department(s) removed)." if result.departments_removed else ".")
    )


# Legacy aliases (hidden)
@org.command("create")
@click.option("--name", required=True, help="Display name for the workspace.")
def org_create(name: str) -> None:
    """[Deprecated] Use 'workspace create' instead."""
    console.print("[yellow]Warning: 'org create' is deprecated. Use 'workspace create'.[/yellow]")
    workspace_create.callback(name=name)


@org.command("list")
def org_list() -> None:
    """[Deprecated] Use 'workspace list' instead."""
    console.print("[yellow]Warning: 'org list' is deprecated. Use 'workspace list'.[/yellow]")
    workspace_list.callback()


@org.command("delete")
@click.option("--slug", required=True, help="Slug of the workspace to delete.")
def org_delete(slug: str) -> None:
    """[Deprecated] Use 'workspace delete' instead."""
    console.print("[yellow]Warning: 'org delete' is deprecated. Use 'workspace delete'.[/yellow]")
    workspace_delete.callback(slug=slug)


# ---------------------------------------------------------------------------
# dept commands
# ---------------------------------------------------------------------------

@cli.group()
def dept() -> None:
    """Manage departments."""


@dept.command("create")
@click.option("--workspace", "workspace_slug", required=True, help="Parent workspace slug.")
@click.option("--name", required=True, help="Display name for the department.")
def dept_create(workspace_slug: str, name: str) -> None:
    """Create a new department under a workspace."""
    with console.status("[cyan]Creating department…[/cyan]", spinner="dots"):
        try:
            result = admin_service.create_department(workspace_slug, name)
        except (admin_service.WorkspaceNotFound, admin_service.DuplicateSlug) as e:
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
@click.option("--workspace", "workspace_slug", default=None, help="Filter by workspace slug.")
def dept_list(workspace_slug: str | None) -> None:
    """List departments, optionally filtered by workspace."""
    try:
        depts = admin_service.list_departments(workspace_slug=workspace_slug)
    except admin_service.WorkspaceNotFound as e:
        print_error(str(e))
        sys.exit(1)

    if workspace_slug:
        print_table(
            f"Departments — {workspace_slug}",
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
            ["ID", "Workspace", "Name", "Slug", "Cache Namespace", "Created"],
            [
                [
                    str(d.id),
                    d.workspace_slug,
                    d.name,
                    d.slug,
                    d.cache_namespace,
                    d.created_at.strftime("%Y-%m-%d %H:%M"),
                ]
                for d in depts
            ],
        )


@dept.command("delete")
@click.option("--workspace", "workspace_slug", required=True, help="Parent workspace slug.")
@click.option("--slug", required=True, help="Department slug to delete.")
def dept_delete(workspace_slug: str, slug: str) -> None:
    """Delete a department."""
    try:
        dept_data = next(
            (dept for dept in admin_service.list_departments(workspace_slug=workspace_slug) if dept.slug == slug),
            None,
        )
    except admin_service.WorkspaceNotFound:
        dept_data = None
    if dept_data is None:
        print_error(f"Department '{slug}' not found under workspace '{workspace_slug}'.")
        sys.exit(1)

    if not Confirm.ask(f"[yellow]Delete department [bold]{slug}[/bold] (namespace: [cyan]{dept_data.cache_namespace}[/cyan])?[/yellow]"):
        print_warning("Aborted.")
        sys.exit(0)

    with console.status("[cyan]Deleting…[/cyan]", spinner="dots"):
        deleted = admin_service.delete_department(workspace_slug, slug)

    print_success(
        f"Department [bold]{slug}[/bold] deleted. "
        f"Freed namespace: [cyan]{deleted.cache_namespace}[/cyan]"
    )


# ---------------------------------------------------------------------------
# key commands
# ---------------------------------------------------------------------------

@cli.group()
def key() -> None:
    """Manage workspace API keys."""


@key.command("generate")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug to generate a key for.")
@click.option("--force", is_flag=True, default=False, help="Revoke existing active key and generate a new one.")
def key_generate(workspace_slug: str, force: bool) -> None:
    """Generate an API key for a workspace."""
    try:
        new_key = admin_service.generate_key(workspace_slug, force=force)
    except admin_service.WorkspaceNotFound:
        print_error(f"Workspace '{workspace_slug}' not found.")
        sys.exit(1)
    except admin_service.ActiveKeyExists as e:
        print_error(
            f"Workspace '{workspace_slug}' already has an active key (id={e.key_id}). "
            "Use --force to revoke it and generate a new one."
        )
        sys.exit(1)

    content = Text()
    content.append("  id           ", style="dim")
    content.append(f"{new_key.id}\n", style="bright_white")
    content.append("  workspace    ", style="dim")
    content.append(f"{workspace_slug}\n", style="bright_white")
    content.append("  token        ", style="dim")
    content.append(f"{new_key.token}\n", style="bold bright_cyan")
    content.append("  created_at   ", style="dim")
    content.append(f"{new_key.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="bright_white")

    console.print(Panel(content, title="[green]API key generated[/green]", border_style="green", padding=(0, 2)))


@key.command("list")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug to list keys for.")
def key_list(workspace_slug: str) -> None:
    """List all API keys for a workspace."""
    try:
        keys = admin_service.list_keys(workspace_slug)
    except admin_service.WorkspaceNotFound:
        print_error(f"Workspace '{workspace_slug}' not found.")
        sys.exit(1)

    if not keys:
        console.print(f"[dim]No API keys found for workspace '{workspace_slug}'.[/dim]")
        return

    print_table(
        f"API Keys — {workspace_slug}",
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
        result = admin_service.revoke_key(key_id)
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
# cache commands
# ---------------------------------------------------------------------------

@cli.group()
def cache() -> None:
    """Maintain cached entries."""


@cache.command("purge-images")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug to purge.")
@click.option("--department", "dept_slug", default=None, help="Limit to one department.")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
@click.option("--dry-run/--no-dry-run", default=True, show_default=True,
              help="Report what would be deleted without deleting it.")
def cache_purge_images(workspace_slug: str, dept_slug: str | None, yes: bool, dry_run: bool) -> None:
    """Delete image-anchored cache entries.

    Run this after a gate rule change: entries stored under the old rules may
    carry fingerprints the current rules would never have accepted. Each purged
    entry simply regenerates on its next request. Text entries are untouched.
    """
    from app.services.memory_chromaDB import get_memory_service

    try:
        departments = admin_service.list_departments(workspace_slug=workspace_slug)
    except admin_service.WorkspaceNotFound:
        print_error(f"Workspace '{workspace_slug}' not found.")
        sys.exit(1)

    if dept_slug:
        departments = [d for d in departments if d.slug == dept_slug]
        if not departments:
            print_error(f"Department '{dept_slug}' not found under workspace '{workspace_slug}'.")
            sys.exit(1)

    namespaces = [d.cache_namespace for d in departments]
    if not dept_slug:
        # Requests without an X-DejaQ-Department header always land here
        # (app/middleware/api_key.py), regardless of whether departments exist.
        namespaces = list(dict.fromkeys(namespaces + [f"{workspace_slug}--default"]))
    found: list[tuple[str, int]] = []
    for namespace in namespaces:
        try:
            found.append((namespace, len(get_memory_service(namespace).image_entry_ids())))
        except Exception as exc:
            print_error(f"Could not read namespace '{namespace}': {exc}")

    total = sum(count for _, count in found)
    print_table(
        "Image entries",
        ["Namespace", "Image entries"],
        [[namespace, str(count)] for namespace, count in found],
    )
    if total == 0:
        print_success("No image entries to purge.")
        return
    if dry_run:
        print_warning(f"Dry run — {total} entr(ies) would be deleted. Re-run with --no-dry-run.")
        return
    if not yes and not Confirm.ask(f"[yellow]Delete [bold]{total}[/bold] image entr(ies)?[/yellow]"):
        print_warning("Aborted.")
        sys.exit(0)

    deleted = 0
    with console.status("[cyan]Purging…[/cyan]", spinner="dots"):
        for namespace, _ in found:
            deleted += get_memory_service(namespace).purge_image_entries()
    print_success(f"Purged {deleted} image entr(ies). They regenerate on the next request.")


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

@cli.command("stats")
def stats_cmd() -> None:
    """Show usage stats: cache hit rates, latency, and model routing per department."""
    _run_stats()


# ---------------------------------------------------------------------------
# rag (Rug) commands — per-workspace knowledge base
# ---------------------------------------------------------------------------

@cli.group()
def rag() -> None:
    """Manage a workspace's RAG (Rug) knowledge base."""


def _rag_service():
    # Imported lazily: pulls in the embedder module, which is heavy to import.
    from app.services import rag_admin_service

    return rag_admin_service


def _print_rag_item(item, title: str) -> None:
    content = Text()
    content.append("  id           ", style="dim")
    content.append(f"{item.id}\n", style="bright_white")
    content.append("  title        ", style="dim")
    content.append(f"{item.title}\n", style="bright_white")
    content.append("  kind         ", style="dim")
    content.append(f"{item.kind} ({item.source})\n", style="bright_white")
    content.append("  chars/chunks ", style="dim")
    content.append(f"{item.char_count:,} / {item.chunk_count}", style="bright_cyan")
    console.print(Panel(content, title=f"[green]{title}[/green]", border_style="green", padding=(0, 2)))


@rag.command("list")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug.")
def rag_list(workspace_slug: str) -> None:
    """List knowledge-base documents for a workspace."""
    svc = _rag_service()
    try:
        docs = svc.list_documents(workspace_slug)
    except admin_service.WorkspaceNotFound as e:
        print_error(str(e))
        sys.exit(1)
    print_table(
        f"Knowledge Base — {workspace_slug}",
        ["ID", "Title", "Kind", "Source", "Chars", "Chunks", "Created"],
        [
            [
                str(d.id),
                d.title[:40],
                d.kind,
                d.source,
                f"{d.char_count:,}",
                str(d.chunk_count),
                d.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
            for d in docs
        ],
    )


@rag.command("add-text")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug.")
@click.option("--title", required=True, help="Title for the knowledge document.")
@click.option("--content", required=True, help="The text to store.")
def rag_add_text(workspace_slug: str, title: str, content: str) -> None:
    """Add a pasted-text knowledge document."""
    svc = _rag_service()
    with console.status("[cyan]Indexing…[/cyan]", spinner="dots"):
        try:
            item = svc.add_text(workspace_slug, title, content)
        except (admin_service.WorkspaceNotFound,
                svc.RagIngestError, svc.RagDisabledError) as e:
            print_error(str(e))
            sys.exit(1)
    _print_rag_item(item, "Knowledge added")


@rag.command("add-file")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug.")
@click.option("--path", "file_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Path to a PDF/DOCX/text/image file.")
@click.option("--title", default=None, help="Override title (defaults to the filename).")
def rag_add_file(workspace_slug: str, file_path: str, title: str | None) -> None:
    """Ingest a file (PDF, DOCX, text/code, or an image to OCR)."""
    import mimetypes
    import os

    svc = _rag_service()
    with open(file_path, "rb") as fh:
        data = fh.read()
    filename = os.path.basename(file_path)
    mime = mimetypes.guess_type(file_path)[0]
    with console.status("[cyan]Extracting + indexing…[/cyan]", spinner="dots"):
        try:
            item = svc.add_upload(workspace_slug, filename, data, mime, title=title)
        except (admin_service.WorkspaceNotFound,
                svc.RagIngestError, svc.RagDisabledError) as e:
            print_error(str(e))
            sys.exit(1)
    _print_rag_item(item, "Knowledge added")


@rag.command("add-url")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug.")
@click.option("--url", required=True, help="Web page URL to ingest.")
@click.option("--title", default=None, help="Override title (defaults to the page title).")
def rag_add_url(workspace_slug: str, url: str, title: str | None) -> None:
    """Ingest the readable text of a web page."""
    svc = _rag_service()
    with console.status("[cyan]Fetching + indexing…[/cyan]", spinner="dots"):
        try:
            item = svc.add_url(workspace_slug, url, title)
        except (admin_service.WorkspaceNotFound,
                svc.RagIngestError, svc.RagDisabledError) as e:
            print_error(str(e))
            sys.exit(1)
    _print_rag_item(item, "Knowledge added")


@rag.command("delete")
@click.option("--workspace", "workspace_slug", required=True, help="Workspace slug.")
@click.option("--id", "doc_id", required=True, type=int, help="Document id to delete.")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
def rag_delete(workspace_slug: str, doc_id: int, yes: bool) -> None:
    """Delete a knowledge document and its chunks."""
    svc = _rag_service()
    if not yes and not Confirm.ask(f"[yellow]Delete knowledge document [bold]{doc_id}[/bold]?[/yellow]"):
        print_warning("Aborted.")
        sys.exit(0)
    with console.status("[cyan]Deleting…[/cyan]", spinner="dots"):
        try:
            svc.delete_document(workspace_slug, doc_id)
        except (admin_service.WorkspaceNotFound, svc.RagDocumentNotFound) as e:
            print_error(str(e))
            sys.exit(1)
    print_success(f"Deleted knowledge document [bold]{doc_id}[/bold].")
