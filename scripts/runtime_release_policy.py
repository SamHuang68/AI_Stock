"""Pure filesystem policy for code artifacts; never resolves a runtime binding.

Reserved data trees are rejected before descending. This applies to legacy
checkouts too: their data directory can contain a later external installation.
"""
from pathlib import Path, PurePosixPath
import os
import stat


RESERVED = frozenset({'runtime', 'recovery'})
PRIVATE_METADATA = frozenset({'.st-data-root.json', '.st-cutover.json',
                              'runtime_binding.json', 'data_binding.json'})


def is_link(path):
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def protected_member(name, *, data_root=False):
    parts = tuple(part.casefold() for part in PurePosixPath(str(name).replace('\\', '/')).parts)
    return (any(part in PRIVATE_METADATA for part in parts)
            or bool(data_root and parts and parts[0] in RESERVED)
            or any(parts[index] == 'data' and parts[index + 1] in RESERVED
                   for index in range(len(parts) - 1)))


def assert_safe_member(name, *, data_root=False):
    if protected_member(name, data_root=data_root):
        raise RuntimeError('protected runtime/recovery content is not a code release input')


def assert_disjoint(paths, protected):
    """Reject operations on either ancestors or descendants of protected roots."""
    for path in paths:
        resolved = Path(path).absolute().resolve()
        for root in protected:
            root = Path(root).absolute().resolve()
            if resolved == root or resolved in root.parents or root in resolved.parents:
                raise RuntimeError('operation overlaps protected runtime/recovery root')


def assert_no_links(path):
    root = Path(path).absolute()
    for part in (root, *root.parents):
        if is_link(part):
            raise RuntimeError('code release input contains a link')


def assert_safe_tree(root):
    """Inspect names only, without entering reserved trees or following links."""
    root = Path(root)
    assert_safe_member(root.as_posix())
    assert_no_links(root)
    if not root.exists():
        return
    data_root = root.name.casefold() == 'data'
    def fail(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        relative = Path(directory).relative_to(root)
        for name in (*dirs, *files):
            path = Path(directory) / name
            assert_safe_member((relative / name).as_posix(), data_root=data_root)
            if is_link(path):
                raise RuntimeError('code release input contains a link')
