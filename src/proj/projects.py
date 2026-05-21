"""Project registry: resolve manifest project entries to runtime Project objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proj.errors import UnknownProjectError
from proj.manifest import Manifest
from proj.paths import resolve_project_path


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    tags: list[str]
    vars: dict[str, str]
    unknown: bool = False


def scan_unknown_subdirs(
    workspace_root: Path,
    claimed_paths: set[Path],
    archive_dir: str | None = None,
) -> list[str]:
    """Return sorted names of subdirs of `workspace_root` not in `claimed_paths`.

    Skips hidden directories and the archive directory.
    """
    if not workspace_root.exists() or not workspace_root.is_dir():
        return []
    out: list[str] = []
    for entry in workspace_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if archive_dir and entry.name == archive_dir:
            continue
        if entry.resolve() in claimed_paths:
            continue
        out.append(entry.name)
    out.sort()
    return out


class ProjectRegistry:
    def __init__(
        self,
        projects: dict[str, Project],
        workspace_root: Path,
        unknown_count: int = 0,
    ) -> None:
        self._projects = projects
        self.workspace_root = workspace_root
        self.unknown_count = unknown_count

    @classmethod
    def from_manifest(
        cls,
        manifest: Manifest,
        include_unknown: bool = True,
    ) -> ProjectRegistry:
        """Build a ProjectRegistry from a manifest, optionally auto-discovering
        workspace subdirectories not declared in `projects:` and adding them as
        Project rows with `unknown=True`.
        """
        projects: dict[str, Project] = {}
        claimed: set[Path] = set()
        for name, entry in manifest.projects.items():
            path = resolve_project_path(name, entry.path_override, manifest.workspace_root)
            projects[name] = Project(
                name=name,
                path=path,
                tags=list(entry.tags),
                vars=dict(entry.vars),
                unknown=False,
            )
            try:
                claimed.add(path.resolve())
            except OSError:
                claimed.add(path)

        unknown_count = 0
        if include_unknown:
            archive_dir = manifest.settings.get("archive_dir", "_archive")
            unknown_names = scan_unknown_subdirs(
                manifest.workspace_root, claimed, archive_dir=str(archive_dir)
            )
            for uname in unknown_names:
                if uname in projects:
                    continue
                upath = manifest.workspace_root / uname
                projects[uname] = Project(name=uname, path=upath, tags=[], vars={}, unknown=True)
                unknown_count += 1
        return cls(projects, manifest.workspace_root, unknown_count=unknown_count)

    def get(self, name: str) -> Project:
        try:
            return self._projects[name]
        except KeyError:
            raise UnknownProjectError(name) from None

    def names(self) -> list[str]:
        return list(self._projects.keys())

    def unknown_names(self) -> list[str]:
        return sorted(p.name for p in self._projects.values() if p.unknown)

    def all_tags(self) -> set[str]:
        tags: set[str] = set()
        for p in self._projects.values():
            tags.update(p.tags)
        return tags

    def __iter__(self):
        return iter(self._projects.values())

    def __len__(self) -> int:
        return len(self._projects)
