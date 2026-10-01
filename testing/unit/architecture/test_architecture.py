import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

from testing.paths import REPOSITORY_ROOT

PACKAGE_ROOT = REPOSITORY_ROOT / "rdmo_sensorsearch"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package = ".".join(path.relative_to(PACKAGE_ROOT.parent).parent.parts)
                module = resolve_name("." * node.level + module, package)
            imported_modules.append(module)
            imported_modules.extend(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
    return imported_modules


def _signal_imports(path: Path) -> list[str]:
    return [module for module in _imports(path) if module.startswith("rdmo_sensorsearch.signals")]


@pytest.mark.parametrize("package_name", ("config_models", "handlers", "services", "workflows", "backends"))
def test_lower_level_packages_do_not_import_signal_adapters(package_name):
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): _signal_imports(path)
        for path in sorted((PACKAGE_ROOT / package_name).rglob("*.py"))
        if _signal_imports(path)
    }

    assert violations == {}


@pytest.mark.parametrize("package_name", ("config_models", "services", "backends"))
def test_framework_independent_packages_do_not_import_django_or_rdmo_models(package_name):
    violations = {}
    for path in sorted((PACKAGE_ROOT / package_name).rglob("*.py")):
        framework_imports = _imports(path)
        framework_imports = [
            module
            for module in framework_imports
            if module == "django" or module.startswith("django.") or module == "rdmo" or module.startswith("rdmo.")
        ]
        if framework_imports:
            violations[str(path.relative_to(PACKAGE_ROOT))] = framework_imports

    assert violations == {}


def test_contracts_import_only_the_standard_library():
    assert {
        module for module in _imports(PACKAGE_ROOT / "contracts.py") if module.partition(".")[0] not in sys.stdlib_module_names
    } == set()


def test_services_do_not_import_implementation_layers_or_configuration_loader():
    forbidden = tuple(
        f"rdmo_sensorsearch.{name}"
        for name in (
            "handlers",
            "workflows",
            "persistence",
            "signals",
            "config",
            "backends",
        )
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): [
            module
            for module in _imports(path)
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
        ]
        for path in (PACKAGE_ROOT / "services").rglob("*.py")
    }
    assert {path: modules for path, modules in violations.items() if modules} == {}


def test_only_scope_adapter_imports_answer_tree():
    violations = {
        str(path.relative_to(PACKAGE_ROOT))
        for path in PACKAGE_ROOT.rglob("*.py")
        if "rdmo.projects.answers" in _imports(path) and path != PACKAGE_ROOT / "persistence" / "scope_resolver.py"
    }
    assert violations == set()


def test_handlers_do_not_import_workflows():
    assert {
        str(path.relative_to(PACKAGE_ROOT))
        for path in (PACKAGE_ROOT / "handlers").rglob("*.py")
        if any(module.startswith("rdmo_sensorsearch.workflows") for module in _imports(path))
    } == set()


def test_handlers_do_not_import_storage_or_frameworks():
    forbidden = (
        "rdmo_sensorsearch.persistence",
        "rdmo_sensorsearch.project_values",
        "rdmo",
        "django",
    )
    assert {
        str(path.relative_to(PACKAGE_ROOT))
        for path in (PACKAGE_ROOT / "handlers").rglob("*.py")
        if any(module == prefix or module.startswith(prefix + ".") for module in _imports(path) for prefix in forbidden)
    } == set()


def test_backends_do_not_import_consumers_or_deployment_infrastructure():
    forbidden = tuple(
        f"rdmo_sensorsearch.{name}"
        for name in (
            "handlers",
            "providers",
            "workflows",
            "persistence",
            "signals",
            "config",
            "client",
            "auth",
            "backend_assembly",
        )
    )
    assert {
        str(path.relative_to(PACKAGE_ROOT))
        for path in (PACKAGE_ROOT / "backends").rglob("*.py")
        if any(module == prefix or module.startswith(prefix + ".") for module in _imports(path) for prefix in forbidden)
    } == set()


def test_sms_consumers_use_capabilities_without_direct_transport_or_concrete_backend_imports():
    consumers = [
        PACKAGE_ROOT / "handlers" / "sms_device.py",
        PACKAGE_ROOT / "handlers" / "sms_configuration.py",
        PACKAGE_ROOT / "handlers" / "sms_device_enrichment.py",
        PACKAGE_ROOT / "providers" / "sms_device.py",
        PACKAGE_ROOT / "providers" / "sms_configuration.py",
    ]
    forbidden = ("rdmo_sensorsearch.client", "rdmo_sensorsearch.backends", "rdmo_sensorsearch.backend_assembly", "requests")
    assert {
        str(path.relative_to(PACKAGE_ROOT))
        for path in consumers
        if any(module == prefix or module.startswith(prefix + ".") for module in _imports(path) for prefix in forbidden)
    } == set()
