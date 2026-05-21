# src/proj/cli.py
"""Command-line entry point for proj."""

from __future__ import annotations

from pathlib import Path

import click

from proj import __version__
from proj.commands import (
    QueryCommand,
    RunCommand,
    merge_commands,
    parse_commands,
)
from proj.defaults_loader import defaults_path, load_defaults
from proj.engine import _ref, build_from_manifest_path, build_query
from proj.grouped import build_grouped_selects
from proj.init import list_subdirectories, render_manifest, write_manifest
from proj.marks import BUNDLED_MARKS, merge_marks, parse_marks
from proj.output import format_grouped_rows, format_rows
from proj.paths import cache_dir as default_cache_dir
from proj.paths import config_path as default_config_path
from proj.paths import projrc_path


class ProjGroup(click.Group):
    """Click group that falls back to user-defined commands on unknown names."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        return _resolve_user_command(ctx, cmd_name)

    def list_commands(self, ctx: click.Context) -> list[str]:
        names = list(super().list_commands(ctx))
        try:
            manifest_path = ctx.params.get("manifest") or default_config_path()
        except Exception:
            return names
        merged = _load_merged_commands(manifest_path)
        if merged is not None:
            for n in merged:
                if n not in names:
                    names.append(n)
        return sorted(names)


def _load_projrc_commands() -> dict:
    """Load ~/.projrc's `commands:` block if present. Returns {} on any error."""
    import yaml

    rc = projrc_path()
    if rc is None:
        return {}
    try:
        data = yaml.safe_load(rc.read_text()) or {}
        return parse_commands(data.get("commands") or {})
    except Exception:
        return {}


def _load_merged_commands(manifest_path: Path):
    """Load defaults.yaml + ~/.projrc + user manifest commands, merged in that order."""
    try:
        defaults_cmds = parse_commands(load_defaults().get("commands"))
    except Exception:
        defaults_cmds = {}
    projrc_cmds = _load_projrc_commands()
    merged = merge_commands(defaults_cmds, projrc_cmds)
    if not manifest_path.exists():
        return merged
    try:
        from proj.manifest import load_manifest

        m = load_manifest(manifest_path)
        user_cmds = parse_commands(m.raw_commands)
    except Exception:
        return merged
    return merge_commands(merged, user_cmds)


def _resolve_user_command(ctx: click.Context, name: str) -> click.Command | None:
    manifest_path = (ctx.params.get("manifest") if ctx.params else None) or default_config_path()
    merged = _load_merged_commands(manifest_path)
    if merged is None or name not in merged:
        return None
    spec = merged[name]
    if isinstance(spec, QueryCommand):
        return _make_query_click(spec)
    return _make_run_click(spec)


def _and_where(a: str | None, b: str | None) -> str | None:
    if a and b:
        return f"({a}) AND ({b})"
    return a or b


def _detect_cwd_project(workspace_root: Path) -> str | None:
    """Walk up from cwd until parent == workspace_root; return the project name, else None."""
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None
    try:
        ws = workspace_root.resolve()
    except OSError:
        return None
    if cwd == ws:
        return None
    cur = cwd
    while cur.parent != cur:
        if cur.parent == ws:
            return cur.name
        cur = cur.parent
    return None


def _apply_scope(
    workspace_root: Path,
    where: str | None,
    *,
    here: bool,
    all_projects: bool,
    default_scope: str,  # "single" or "aggregate"
) -> str | None:
    """Merge --here/--all + auto-scope into a SQL where-clause."""
    if all_projects and here:
        raise click.UsageError("--here and --all are mutually exclusive")
    if all_projects:
        return where
    if here:
        name = _detect_cwd_project(workspace_root)
        if name is None:
            raise click.UsageError("--here: cwd is not inside the workspace")
        return _and_where(where, f"name = '{name}'")
    # No explicit scope: apply default.
    if default_scope == "single":
        name = _detect_cwd_project(workspace_root)
        if name is not None:
            return _and_where(where, f"name = '{name}'")
    return where


def _emit_unknown_warning(engine) -> None:
    """Emit a stderr footer when settings.unknown_handling = warn and unknowns exist."""
    if engine.unknown_handling == "warn" and engine.unknown_count > 0:
        click.echo(
            f"warning: {engine.unknown_count} unknown subdirector"
            f"{'y' if engine.unknown_count == 1 else 'ies'} not in manifest "
            f"(run `proj adopt` to promote)",
            err=True,
        )


def _make_query_click(spec: QueryCommand) -> click.Command:
    @click.command(name=spec.name, help=f"User-defined query command ({spec.name}).")
    @click.option(
        "--where", default=None, help="Extra SQL WHERE (AND-merged with command's where)."
    )
    @click.option("--order-by", default=None, help="Override command's order_by.")
    @click.option("--limit", type=int, default=None, help="Override command's limit.")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json", "plain"]),
        default="table",
    )
    @click.pass_context
    def cmd(
        ctx: click.Context,
        where: str | None,
        order_by: str | None,
        limit: int | None,
        output_format: str,
    ) -> None:
        from proj.manifest import load_manifest

        manifest_path: Path = ctx.obj["manifest"]
        cdir: Path = ctx.obj["cache_dir"]
        if not manifest_path.exists():
            raise click.UsageError(f"Manifest not found at {manifest_path}")
        engine = build_from_manifest_path(manifest_path, cache_path=cdir / "cache.db")
        _emit_unknown_warning(engine)
        user_select_parts = [_ref(c) for c in spec.columns]
        grouped_select_parts = build_grouped_selects(spec.grouped_columns)
        select = ", ".join(user_select_parts + grouped_select_parts)
        sql = build_query(
            select,
            where=_and_where(spec.where, where),
            order_by=order_by or spec.order_by,
            limit=limit if limit is not None else spec.limit,
        )
        try:
            cursor = engine.execute(sql)
        except Exception as e:
            raise click.ClickException(f"query failed: {e}") from e
        headers = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        if spec.grouped_columns:
            m = load_manifest(manifest_path)
            user_marks = parse_marks(m.raw_marks)
            marks = merge_marks(BUNDLED_MARKS, user_marks)
            format_grouped_rows(
                rows,
                headers,
                spec.columns,
                spec.grouped_columns,
                marks,
                fmt=output_format,
            )
        else:
            format_rows(rows, headers, fmt=output_format)

    return cmd


def _make_run_click(spec: RunCommand) -> click.Command:
    @click.command(name=spec.name, help=f"User-defined run command ({spec.name}).")
    @click.option(
        "--where", default=None, help="Extra SQL filter (AND-merged with command's where)."
    )
    @click.option("--dry-run", is_flag=True, help="Print commands without executing.")
    @click.option("--parallel", is_flag=True, help="Run projects concurrently.")
    @click.option("--summary", is_flag=True, help="Print a pass/fail summary at the end.")
    @click.option("--here", is_flag=True, help="Scope to the current project (cwd).")
    @click.option("--all", "all_projects", is_flag=True, help="Force workspace scope.")
    @click.pass_context
    def cmd(
        ctx: click.Context,
        where: str | None,
        dry_run: bool,
        parallel: bool,
        summary: bool,
        here: bool,
        all_projects: bool,
    ) -> None:
        from proj.manifest import load_manifest
        from proj.projects import ProjectRegistry
        from proj.run import execute_run

        manifest_path: Path = ctx.obj["manifest"]
        cdir: Path = ctx.obj["cache_dir"]
        if not manifest_path.exists():
            raise click.UsageError(f"Manifest not found at {manifest_path}")
        m = load_manifest(manifest_path)
        engine = build_from_manifest_path(manifest_path, cache_path=cdir / "cache.db")
        _emit_unknown_warning(engine)
        archive_dir = str(m.settings.get("archive_dir", "_archive"))
        registry = ProjectRegistry.from_manifest(m, include_unknown=True)
        scoped_where = _apply_scope(
            m.workspace_root,
            _and_where(spec.where, where),
            here=here,
            all_projects=all_projects,
            default_scope="single",
        )
        failures = execute_run(
            engine,
            spec.cmds,
            scoped_where,
            m.workspace_root,
            archive_dir,
            dry_run,
            project_registry=registry,
            parallel=parallel,
            summary=summary,
        )
        ctx.exit(min(failures, 125))

    return cmd


@click.group(cls=ProjGroup)
@click.version_option(__version__, prog_name="proj")
@click.option(
    "--manifest",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to projects.yaml (defaults to ~/.config/proj/projects.yaml).",
)
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Cache directory (defaults to ~/.cache/proj).",
)
@click.pass_context
def main(ctx: click.Context, manifest: Path | None, cache_dir: Path | None) -> None:
    """Manage a flat directory of heterogeneous projects."""
    ctx.ensure_object(dict)
    ctx.obj["manifest"] = manifest or default_config_path()
    ctx.obj["cache_dir"] = cache_dir or default_cache_dir()


@main.command()
@click.argument("input")
@click.option("--where", help="SQL WHERE clause.")
@click.option("--order-by", help="SQL ORDER BY clause.")
@click.option("--group-by", help="SQL GROUP BY clause.")
@click.option("--limit", type=int, help="SQL LIMIT.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "plain"]),
    default="table",
)
@click.pass_context
def query(
    ctx: click.Context,
    input: str,
    where: str | None,
    order_by: str | None,
    group_by: str | None,
    limit: int | None,
    output_format: str,
) -> None:
    """Run a SQL query against the projects table."""
    manifest_path: Path = ctx.obj["manifest"]
    cdir: Path = ctx.obj["cache_dir"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")
    engine = build_from_manifest_path(manifest_path, cache_path=cdir / "cache.db")
    _emit_unknown_warning(engine)
    sql = build_query(input, where=where, order_by=order_by, group_by=group_by, limit=limit)
    try:
        cursor = engine.execute(sql)
    except Exception as e:
        raise click.ClickException(f"query failed: {e}") from e
    headers = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    format_rows(rows, headers, fmt=output_format)


@main.command()
@click.argument(
    "directory",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    required=False,
)
@click.option("--force", is_flag=True, help="Overwrite an existing manifest.")
@click.pass_context
def init(ctx: click.Context, directory: Path | None, force: bool) -> None:
    """Bootstrap a projects.yaml from a workspace directory.

    Each immediate subdirectory of DIRECTORY (or the current directory) becomes
    a project entry. The manifest is written to ~/.config/proj/projects.yaml
    unless --manifest was passed.
    """
    root = (directory or Path.cwd()).expanduser().resolve()
    if not root.is_dir():
        raise click.UsageError(f"not a directory: {root}")

    manifest_path: Path = ctx.obj["manifest"]
    if manifest_path.exists() and not force:
        raise click.UsageError(
            f"manifest already exists at {manifest_path} (use --force to overwrite)"
        )

    names = list_subdirectories(root)
    content = render_manifest(root, names)
    write_manifest(manifest_path, content)

    click.echo(f"wrote {manifest_path}")
    click.echo(f"workspace.root: {root}")
    if names:
        click.echo(
            f"projects: {len(names)} ({', '.join(names[:5])}{'...' if len(names) > 5 else ''})"
        )
    else:
        click.echo("projects: 0 (add entries to the manifest, then re-run)")


@main.command()
@click.argument("cmd")
@click.option("--where", default=None, help="SQL filter on the projects table.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--parallel", is_flag=True, help="Run projects concurrently.")
@click.option("--summary", is_flag=True, help="Print a pass/fail summary at the end.")
@click.option("--here", is_flag=True, help="Scope to the current project (cwd).")
@click.option("--all", "all_projects", is_flag=True, help="Force workspace scope.")
@click.pass_context
def run(
    ctx: click.Context,
    cmd: str,
    where: str | None,
    dry_run: bool,
    parallel: bool,
    summary: bool,
    here: bool,
    all_projects: bool,
) -> None:
    """Run a shell command per matching project."""
    from proj.manifest import load_manifest
    from proj.projects import ProjectRegistry
    from proj.run import execute_run

    manifest_path: Path = ctx.obj["manifest"]
    cdir: Path = ctx.obj["cache_dir"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")
    m = load_manifest(manifest_path)
    engine = build_from_manifest_path(manifest_path, cache_path=cdir / "cache.db")
    _emit_unknown_warning(engine)
    archive_dir = str(m.settings.get("archive_dir", "_archive"))
    registry = ProjectRegistry.from_manifest(m, include_unknown=True)
    scoped_where = _apply_scope(
        m.workspace_root, where, here=here, all_projects=all_projects, default_scope="single"
    )
    failures = execute_run(
        engine,
        [cmd],
        scoped_where,
        m.workspace_root,
        archive_dir,
        dry_run,
        project_registry=registry,
        parallel=parallel,
        summary=summary,
    )
    ctx.exit(min(failures, 125))


@main.command()
@click.argument("name")
@click.pass_context
def forget(ctx: click.Context, name: str) -> None:
    """Remove a project entry from the manifest. Does not touch the filesystem."""
    from proj.manifest_edit import dump_after_edit, load_for_edit, remove_project

    manifest_path: Path = ctx.obj["manifest"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")
    data = load_for_edit(manifest_path)
    try:
        remove_project(data, name)
    except KeyError:
        raise click.UsageError(f"unknown project: {name}") from None
    dump_after_edit(manifest_path, data)
    click.echo(f"forgot {name}")


@main.command()
@click.argument("subdir", required=False)
@click.option(
    "--tags",
    default=None,
    help="Comma-separated tags (skips the interactive prompt).",
)
@click.option("--list", "list_only", is_flag=True, help="List unknown subdirectories and exit.")
@click.pass_context
def adopt(
    ctx: click.Context,
    subdir: str | None,
    tags: str | None,
    list_only: bool,
) -> None:
    """Promote an unknown subdirectory to a declared project."""
    from proj.manifest import load_manifest
    from proj.manifest_edit import add_project, dump_after_edit, load_for_edit
    from proj.projects import scan_unknown_subdirs

    manifest_path: Path = ctx.obj["manifest"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")

    m = load_manifest(manifest_path)
    archive_dir = str(m.settings.get("archive_dir", "_archive"))
    claimed = set()
    for entry_name, entry in m.projects.items():
        from proj.paths import resolve_project_path

        claimed.add(
            resolve_project_path(entry_name, entry.path_override, m.workspace_root).resolve()
        )
    unknowns = scan_unknown_subdirs(m.workspace_root, claimed, archive_dir=archive_dir)

    if list_only:
        if not unknowns:
            click.echo("(no unknown subdirectories)")
            return
        for u in unknowns:
            click.echo(u)
        return

    if subdir is None:
        if not unknowns:
            click.echo("(no unknown subdirectories to adopt)")
            return
        click.echo("Unknown subdirectories:")
        for i, u in enumerate(unknowns, 1):
            click.echo(f"  {i}. {u}")
        choice = click.prompt("Pick one (number or name)", type=str, default=unknowns[0])
        if choice.isdigit() and 1 <= int(choice) <= len(unknowns):
            subdir = unknowns[int(choice) - 1]
        else:
            subdir = choice

    if subdir not in unknowns:
        raise click.UsageError(f"{subdir!r} is not an unknown subdirectory of {m.workspace_root}")

    if tags is None:
        tags_input = click.prompt(
            "Tags (comma-separated, blank for none)", default="", show_default=False
        )
    else:
        tags_input = tags
    tag_list = [t.strip() for t in tags_input.split(",") if t.strip()]

    data = load_for_edit(manifest_path)
    try:
        add_project(data, subdir, tag_list)
    except KeyError as e:
        raise click.ClickException(str(e)) from e
    dump_after_edit(manifest_path, data)
    click.echo(f"adopted {subdir} with tags {tag_list}")


@main.command(name="new")
@click.argument("template")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Print template commands without executing.")
@click.pass_context
def new_cmd(ctx: click.Context, template: str, name: str, dry_run: bool) -> None:
    """Scaffold a new project from a template, then auto-adopt it."""
    from proj.manifest import load_manifest
    from proj.manifest_edit import add_project, dump_after_edit, load_for_edit
    from proj.templates import parse_templates, run_template

    manifest_path: Path = ctx.obj["manifest"]
    if not manifest_path.exists():
        raise click.UsageError(f"Manifest not found at {manifest_path}")

    m = load_manifest(manifest_path)
    templates = parse_templates(m.raw_templates)
    if template not in templates:
        raise click.UsageError(
            f"template {template!r} not in manifest. Available: {sorted(templates)}"
        )
    if name in m.projects:
        raise click.UsageError(f"project {name!r} already declared in manifest")

    tmpl = templates[template]
    failing_idx, results = run_template(tmpl, name, m.workspace_root, dry_run=dry_run)

    if dry_run:
        for r in results:
            click.echo(r.cmd)
        return

    if failing_idx >= 0:
        click.echo(
            f"template step {failing_idx + 1} failed (exit {results[failing_idx].returncode}): "
            f"{results[failing_idx].cmd}",
            err=True,
        )
        click.echo(
            "partial state left in place; resolve manually before re-running",
            err=True,
        )
        ctx.exit(1)

    data = load_for_edit(manifest_path)
    try:
        add_project(data, name, tmpl.tags)
    except KeyError as e:
        raise click.ClickException(str(e)) from e
    dump_after_edit(manifest_path, data)
    click.echo(f"created {name} with tags {tmpl.tags}")


@main.command()
@click.option("--path", "show_path", is_flag=True, help="Print the file path instead of contents.")
def defaults(show_path: bool) -> None:
    """Print the bundled defaults.yaml (or its path)."""
    if show_path:
        click.echo(str(defaults_path()))
    else:
        click.echo(defaults_path().read_text(), nl=False)


if __name__ == "__main__":
    main()
