"""Dispatch functions: resolve column values and applicability per project."""

from __future__ import annotations

import logging
from typing import Any

from proj.cache import Cache
from proj.columns import ColumnRegistry, coerce_to_type, make_shell_evaluator
from proj.errors import UnknownColumnError, UnknownProjectError
from proj.interpolation import interpolate
from proj.projects import Project, ProjectRegistry

log = logging.getLogger(__name__)

_APPLIES_SHELL = make_shell_evaluator()


class Dispatcher:
    def __init__(self, columns: ColumnRegistry, projects: ProjectRegistry, cache: Cache) -> None:
        self.columns = columns
        self.projects = projects
        self.cache = cache

    def _project_vars(self, p: Project) -> dict[str, str]:
        return {
            "name": p.name,
            "path": str(p.path),
            "workspace_root": str(self.projects.workspace_root),
            **p.vars,
        }

    def get_applies(self, project_name: str, column_name: str) -> int:
        try:
            project = self.projects.get(project_name)
            spec = self.columns.get(column_name)
        except (UnknownProjectError, UnknownColumnError):
            return 0
        if spec.applies_when is None:
            return 1
        try:
            rendered = interpolate(spec.applies_when, self._project_vars(project))
        except KeyError as e:
            log.warning("column %s on %s: %s", column_name, project_name, e)
            return 0
        key = Cache.command_hash(rendered)
        cached = self.cache.lookup(project_name, f"{column_name}__applies", key)
        if cached is not None:
            return int(cached)
        result = _APPLIES_SHELL(rendered, project.path)
        applies = 1 if result is not None else 0
        self.cache.store(project_name, f"{column_name}__applies", key, applies)
        return applies

    def get_value(self, project_name: str, column_name: str) -> Any:
        try:
            project = self.projects.get(project_name)
            spec = self.columns.get(column_name)
        except (UnknownProjectError, UnknownColumnError):
            return None

        if self.get_applies(project_name, column_name) == 0:
            return None

        try:
            rendered = interpolate(spec.value_from_template or "", self._project_vars(project))
        except KeyError as e:
            log.warning("column %s on %s: %s", column_name, project_name, e)
            return None
        if spec.value_from_template:
            key = Cache.command_hash(rendered)
        else:
            try:
                dir_mtime = int(project.path.stat().st_mtime)
            except OSError:
                dir_mtime = 0
            key = f"static:{column_name}:{dir_mtime}"

        if spec.cache:
            cached = self.cache.lookup(project_name, column_name, key)
            if cached is not None:
                return cached

        try:
            raw = spec.evaluator(rendered, project.path)
        except Exception as e:
            log.warning("column %s on %s failed: %s", column_name, project_name, e)
            return None

        value = coerce_to_type(raw, spec.type)
        if spec.cache and value is not None:
            self.cache.store(project_name, column_name, key, value)
        return value
