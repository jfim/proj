"""Domain-specific exceptions for proj."""


class ProjError(Exception):
    """Base class for all proj errors."""


class ManifestError(ProjError):
    """Raised when the manifest is malformed or invalid."""


class UnknownColumnError(ProjError):
    """Raised when a column referenced in config or a query is not registered."""


class UnknownProjectError(ProjError):
    """Raised when a project name is not in the registry."""


class ReservedNameError(ManifestError):
    """Raised when the manifest uses a reserved name (e.g., column ending in _applies)."""
