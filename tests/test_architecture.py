import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "rdmo_sensorsearch"


def _signal_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
    return [module for module in imported_modules if module.startswith("rdmo_sensorsearch.signals")]


@pytest.mark.parametrize("package_name", ("handlers", "services", "workflows"))
def test_lower_level_packages_do_not_import_signal_adapters(package_name):
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): _signal_imports(path)
        for path in sorted((PACKAGE_ROOT / package_name).glob("*.py"))
        if _signal_imports(path)
    }

    assert violations == {}


def test_services_do_not_import_django_or_rdmo_models():
    violations = {}
    for path in sorted((PACKAGE_ROOT / "services").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        framework_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                framework_imports.append(node.module)
            elif isinstance(node, ast.Import):
                framework_imports.extend(alias.name for alias in node.names)
        framework_imports = [
            module
            for module in framework_imports
            if module == "django" or module.startswith("django.") or module == "rdmo" or module.startswith("rdmo.")
        ]
        if framework_imports:
            violations[str(path.relative_to(PACKAGE_ROOT))] = framework_imports

    assert violations == {}
