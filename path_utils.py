"""Shared lexical path rules for dependency selection and copying."""

from typing import Iterable, List, Sequence


def _clean_path(path: str) -> str:
    cleaned = path.strip()
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned


def _parse_path_list(raw: str | None) -> List[str]:
    if not raw:
        return []

    seen = set()
    paths = []
    for piece in raw.split(","):
        path = _clean_path(piece)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _path_is_under(path: str, root: str) -> bool:
    path = _clean_path(path)
    root = _clean_path(root)
    return path == root or path.startswith(root + "/")


def _path_is_under_any(path: str, roots: Iterable[str]) -> bool:
    return any(_path_is_under(path, root) for root in roots)


def _apply_path_overrides(
    detected_paths: Sequence[str],
    include_paths: Sequence[str],
    exclude_paths: Sequence[str],
) -> List[str]:
    """
    --inc force-adds paths.
    --exc removes detected or forced paths.
    If a path is both included and excluded, exclusion wins.
    """
    merged = {_clean_path(p) for p in detected_paths if _clean_path(p)}
    merged.update(_clean_path(p) for p in include_paths if _clean_path(p))

    if exclude_paths:
        merged = {p for p in merged if not _path_is_under_any(p, exclude_paths)}

    return sorted(merged)
