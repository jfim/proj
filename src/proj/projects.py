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


class ProjectRegistry:
    def __init__(self, projects: dict[str, Project], workspace_root: Path) -> None:
        self._projects = projects
        self.workspace_root = workspace_root

    @classmethod
    def from_manifest(cls, manifest: Manifest) -> ProjectRegistry:
        projects: dict[str, Project] = {}
        for name, entry in manifest.projects.items():
            path = resolve_project_path(name, entry.path_override, manifest.workspace_root)
            projects[name] = Project(name=name, path=path, tags=list(entry.tags), vars=dict(entry.vars))
        return cls(projects, manifest.workspace_root)

    def get(self, name: str) -> Project:
        try:
            return self._projects[name]
        except KeyError:
            raise UnknownProjectError(name) from None

    def names(self) -> list[str]:
        return list(self._projects.keys())

    def all_tags(self) -> set[str]:
        tags: set[str] = set()
        for p in self._projects.values():
            tags.update(p.tags)
        return tags

    def __iter__(self):
        return iter(self._projects.values())

    def __len__(self) -> int:
        return len(self._projects)
