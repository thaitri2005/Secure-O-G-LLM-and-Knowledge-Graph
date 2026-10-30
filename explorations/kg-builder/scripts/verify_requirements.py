"""Check the active interpreter against an offline requirements pin file."""
import importlib.metadata
import sys
from pathlib import Path
from packaging.requirements import Requirement


def verify(path):
    checked = 0
    errors = []
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
            if not requirement.specifier.contains(installed):
                errors.append(f'{requirement.name}: {installed} does not satisfy {requirement.specifier}')
        except importlib.metadata.PackageNotFoundError:
            errors.append(f'{requirement.name}: missing')
        checked += 1
    if errors:
        raise RuntimeError('\n'.join(errors))
    print(f'{Path(path).name}: {checked} package pins verified')


if __name__ == '__main__':
    verify(sys.argv[1])
