from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_PLUGIN_JSON = REPO_ROOT / ".codex-plugin" / "plugin.json"
CODEX_MARKETPLACE_JSON = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
ROOT_MARKETPLACE_JSON = REPO_ROOT / "marketplace.json"
CODEX_MARKETPLACE_PLUGIN_PATH = REPO_ROOT / "plugins" / "mst"
SKILLS_DIR = REPO_ROOT / "skills"


ALLOWED_CODEX_MANIFEST_KEYS = {
    "id",
    "name",
    "version",
    "description",
    "skills",
    "apps",
    "mcpServers",
    "interface",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
}
REQUIRED_INTERFACE_FIELDS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
}
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


def _manifest() -> dict:
    return json.loads(CODEX_PLUGIN_JSON.read_text(encoding="utf-8"))


def _marketplace() -> dict:
    return json.loads(CODEX_MARKETPLACE_JSON.read_text(encoding="utf-8"))


def _root_marketplace() -> dict:
    return json.loads(ROOT_MARKETPLACE_JSON.read_text(encoding="utf-8"))


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    end = text.find("\n---", 4)
    assert end != -1
    fields: dict[str, str] = {}
    for raw_line in text[4:end].splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def test_codex_manifest_uses_supported_fields_only() -> None:
    manifest = _manifest()

    assert set(manifest) <= ALLOWED_CODEX_MANIFEST_KEYS
    assert "hooks" not in manifest
    assert "agents" not in manifest


def test_codex_manifest_declares_installable_skill_surface() -> None:
    manifest = _manifest()

    assert manifest["name"] == "mst"
    assert SEMVER_RE.fullmatch(manifest["version"])
    assert manifest["skills"] == "./skills/"
    assert isinstance(manifest["author"], dict)
    assert manifest["author"]["name"]


def test_codex_manifest_interface_metadata_is_complete() -> None:
    interface = _manifest()["interface"]

    assert REQUIRED_INTERFACE_FIELDS <= set(interface)
    for field in REQUIRED_INTERFACE_FIELDS:
        assert isinstance(interface[field], str)
        assert interface[field].strip()
    assert isinstance(interface["capabilities"], list)
    assert all(isinstance(value, str) and value.strip() for value in interface["capabilities"])
    assert isinstance(interface["defaultPrompt"], list)
    assert 1 <= len(interface["defaultPrompt"]) <= 3
    assert all(isinstance(value, str) and 0 < len(value) <= 128 for value in interface["defaultPrompt"])


def test_codex_marketplace_entry_points_at_repository_plugin() -> None:
    manifest = _manifest()
    marketplace = _marketplace()
    plugins = marketplace["plugins"]

    assert marketplace["name"] == "gran-maestro"
    assert isinstance(plugins, list)
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin["name"] == manifest["name"]
    assert plugin["version"] == manifest["version"]
    assert plugin["author"]["name"] == manifest["author"]["name"]
    assert plugin["source"] == {"source": "local", "path": "./plugins/mst"}
    projection_manifest = CODEX_MARKETPLACE_PLUGIN_PATH / ".codex-plugin" / "plugin.json"
    assert projection_manifest.is_file()
    assert json.loads(projection_manifest.read_text(encoding="utf-8")) == manifest
    assert plugin["policy"]["installation"] == "AVAILABLE"
    assert plugin["policy"]["authentication"] == "ON_INSTALL"
    assert plugin["category"] == "productivity"
    assert plugin["homepage"] == manifest["homepage"] == manifest["repository"]


def test_codex_marketplace_source_exposes_copy_projection_without_claude_surfaces() -> None:
    assert CODEX_MARKETPLACE_PLUGIN_PATH.is_dir()
    assert not CODEX_MARKETPLACE_PLUGIN_PATH.is_symlink()
    assert (CODEX_MARKETPLACE_PLUGIN_PATH / "skills").is_dir()
    assert sorted(
        path.name
        for path in (CODEX_MARKETPLACE_PLUGIN_PATH / "skills").iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ) == sorted(path.name for path in SKILLS_DIR.iterdir() if path.is_dir() and not path.name.startswith("."))
    assert not (CODEX_MARKETPLACE_PLUGIN_PATH / ".claude-plugin").exists()
    assert not (CODEX_MARKETPLACE_PLUGIN_PATH / ".claude").exists()


def test_root_marketplace_mirrors_repo_local_codex_marketplace() -> None:
    assert _root_marketplace() == _marketplace()


def test_codex_skill_directory_children_are_manifest_parseable() -> None:
    missing = []
    invalid = []

    for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir() and not path.name.startswith(".")):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            missing.append(str(skill_md.relative_to(REPO_ROOT)))
            continue
        frontmatter = _frontmatter(skill_md.read_text(encoding="utf-8"))
        if frontmatter.get("name") != skill_dir.name:
            invalid.append(f"{skill_md.relative_to(REPO_ROOT)} name={frontmatter.get('name')!r}")
        if not frontmatter.get("description"):
            invalid.append(f"{skill_md.relative_to(REPO_ROOT)} missing description")

    assert not missing
    assert not invalid
