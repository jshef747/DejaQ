import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_model

# Every module allowed to `import litellm`. Grows by exactly one entry per
# migration stage that legitimately needs it (model_catalog.py in stage A1);
# nothing else may ever import it. Written now, before there is anything to
# enforce, so the rule predates the temptation (migration plan §4, exit seam 1).
_ALLOWED_IMPORTERS = {
    "app/services/llm_providers/_litellm_config.py",
    "app/services/llm_providers/litellm_transport.py",
}

_APP_ROOT = Path(__file__).resolve().parent.parent / "app"


def _imports_litellm(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "litellm" or alias.name.startswith("litellm.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "litellm" or node.module.startswith("litellm.")):
                return True
    return False


def test_litellm_is_imported_in_exactly_the_allowed_modules() -> None:
    importers = {
        str(path.relative_to(_APP_ROOT.parent))
        for path in _APP_ROOT.rglob("*.py")
        if _imports_litellm(path)
    }

    assert importers == _ALLOWED_IMPORTERS
