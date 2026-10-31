"""Content-derived file identifiers and deterministic local sequences."""


def file_id(sha256: str) -> str:
    return 'f' + sha256[:16]


def child_id(parent: str, index: int) -> str:
    return f'{parent}:c{index}'
