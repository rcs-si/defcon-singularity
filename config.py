"""Load site settings from the TOML file beside this module, independent of cwd."""

from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:
        raise ImportError(
            "DEFCON requires Python 3.11+ or tomli: python3 -m pip install -r requirements.txt"
        ) from exc


CONFIG_PATH = Path(__file__).resolve().with_name("defcon.toml")


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Read and validate site settings; report configuration errors at startup."""
    with path.open("rb") as source:
        settings = tomllib.load(source)
    strings = ("DEFAULT_BASE_IMAGE", "MODULE_INSTALL_PATTERN",
               "NVIDIA_TOOLKIT_PATTERN", "AMD_TOOLKIT_PATTERN")
    arrays = ("IGNORE_PREFIXES", "INTERESTING_PREFIXES", "MODULE_PATH_PREFIXES",
              "MODULE_BLOCKLIST", "NVIDIA_MODULES", "AMD_MODULES", "MPI_MODULES")
    for key in strings:
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise ValueError(f"{path}: {key} must be a nonempty string")
    for key in arrays:
        value = settings.get(key)
        if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
            raise ValueError(f"{path}: {key} must be an array of nonempty strings")
    for key in ("MODULE_INSTALL_PATTERN", "NVIDIA_TOOLKIT_PATTERN", "AMD_TOOLKIT_PATTERN"):
        try:
            pattern = re.compile(settings[key])
        except re.error as exc:
            raise ValueError(f"{path}: invalid {key}: {exc}") from exc
        required = {"root", "name", "version"} if key == "MODULE_INSTALL_PATTERN" else {"root"}
        if not required.issubset(pattern.groupindex):
            raise ValueError(f"{path}: {key} requires named groups {sorted(required)}")
    return settings


_settings = load_config()
DEFAULT_BASE_IMAGE = _settings["DEFAULT_BASE_IMAGE"]
IGNORE_PREFIXES = tuple(_settings["IGNORE_PREFIXES"])
INTERESTING_PREFIXES = tuple(_settings["INTERESTING_PREFIXES"])
MODULE_PATH_PREFIXES = tuple(_settings["MODULE_PATH_PREFIXES"])
MODULE_BLOCKLIST = frozenset(_settings["MODULE_BLOCKLIST"])
MODULE_INSTALL_RE = re.compile(_settings["MODULE_INSTALL_PATTERN"])
NVIDIA_TOOLKIT_RE = re.compile(_settings["NVIDIA_TOOLKIT_PATTERN"])
AMD_TOOLKIT_RE = re.compile(_settings["AMD_TOOLKIT_PATTERN"])
NVIDIA_MODULES = frozenset(_settings["NVIDIA_MODULES"])
AMD_MODULES = frozenset(_settings["AMD_MODULES"])
MPI_MODULES = frozenset(_settings["MPI_MODULES"])
