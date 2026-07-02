import json
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"
GITIGNORE = Path(__file__).parent.parent / ".gitignore"


def test_package_json_declares_openapi_fetch_dependency() -> None:
    data = json.loads((FRONTEND / "package.json").read_text())
    assert "openapi-fetch" in data["dependencies"]


def test_package_json_declares_openapi_typescript_devdependency() -> None:
    data = json.loads((FRONTEND / "package.json").read_text())
    assert "openapi-typescript" in data["devDependencies"]
    assert "openapi-typescript" not in data["dependencies"]


def test_package_json_generate_types_script_targets_openapi_json() -> None:
    data = json.loads((FRONTEND / "package.json").read_text())
    script = data["scripts"]["generate-types"]
    assert "openapi-typescript" in script
    assert "/openapi.json" in script
    assert "-o" in script


def test_api_client_module_imports_openapi_fetch_and_generated_schema() -> None:
    content = (FRONTEND / "src" / "api" / "client.ts").read_text()
    assert "openapi-fetch" in content
    assert "./schema" in content
    assert "createClient" in content


def test_generated_schema_file_exists_and_is_not_empty() -> None:
    schema = FRONTEND / "src" / "api" / "schema.d.ts"
    assert schema.exists()
    assert "export interface paths" in schema.read_text()


def test_generated_schema_file_is_not_gitignored() -> None:
    assert "schema.d.ts" not in GITIGNORE.read_text()
