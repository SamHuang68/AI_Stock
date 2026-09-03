#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integrity, privacy and static-boundary checks for ST Archify documents."""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs" / "architecture" / "archify-manifest.json"

EXPECTED_ARTIFACTS = {
    "st-decision-evidence-lineage": (
        "dataflow",
        "docs/architecture/st-decision-evidence-lineage.dataflow.json",
        "assets/docs/archify/st-decision-evidence-lineage.html",
    ),
    "st-private-web-trust-ai-execution": (
        "architecture",
        "docs/architecture/st-private-web-trust-ai-execution.architecture.json",
        "assets/docs/archify/st-private-web-trust-ai-execution.html",
    ),
    "st-private-web-release-gate": (
        "workflow",
        "docs/architecture/st-private-web-release-gate.workflow.json",
        "assets/docs/archify/st-private-web-release-gate.html",
    ),
    "st-pulse-refresh-degradation": (
        "sequence",
        "docs/architecture/st-pulse-refresh-degradation.sequence.json",
        "assets/docs/archify/st-pulse-refresh-degradation.html",
    ),
    "st-responsive-shell-ownership": (
        "workflow",
        "docs/architecture/st-responsive-shell-ownership.workflow.json",
        "assets/docs/archify/st-responsive-shell-ownership.html",
    ),
    "st-signal-passport-early-warning": (
        "lifecycle",
        "docs/architecture/st-signal-passport-early-warning.lifecycle.json",
        "assets/docs/archify/st-signal-passport-early-warning.html",
    ),
}

EXPECTED_VIEWPORTS = {"1440x900", "1600x1000", "1920x1080", "2048x1320"}
ALLOWED_EXTERNAL_LINK_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}


def _reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _strict_json_bytes(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_members)


def _strict_json_file(path: Path) -> object:
    return _strict_json_bytes(path.read_bytes())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contained_repo_file(relative: object) -> Path:
    value = str(relative or "")
    pure = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or pure.is_absolute()
        or ".." in pure.parts
        or pure.as_posix() != value
    ):
        raise AssertionError(f"unsafe repository-relative path: {value!r}")
    resolved = (ROOT / Path(*pure.parts)).resolve()
    resolved.relative_to(ROOT.resolve())
    if not resolved.is_file():
        raise AssertionError(f"manifest target is missing: {value}")
    return resolved


class _ResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append((tag.lower(), {str(k).lower(): str(v or "") for k, v in attrs}))


class ArchifyArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = _strict_json_file(MANIFEST_PATH)
        if not isinstance(value, dict):
            raise AssertionError("Archify manifest must be a JSON object")
        cls.manifest = value
        artifacts = value.get("artifacts")
        if not isinstance(artifacts, list):
            raise AssertionError("Archify manifest artifacts must be a list")
        if len(artifacts) != len(EXPECTED_ARTIFACTS):
            raise AssertionError("Archify manifest must contain exactly six artifacts")
        cls.by_id = {str(row.get("id") or ""): row for row in artifacts}

    def test_duplicate_json_members_are_rejected_at_every_depth(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON member: a"):
            _strict_json_bytes(b'{"outer":{"a":1,"a":2}}')

    def test_manifest_has_exact_versioned_inventory_and_policy(self):
        self.assertEqual(self.manifest.get("schemaVersion"), "st-archify-manifest/v1")
        self.assertEqual(set(self.by_id), set(EXPECTED_ARTIFACTS))
        self.assertEqual(len(self.by_id), len(EXPECTED_ARTIFACTS))

        source = self.manifest.get("source") or {}
        repository_url = str(source.get("repositoryUrl") or "")
        self.assertRegex(repository_url, r"^https://[^\s]+$")
        self.assertRegex(str(source.get("commit") or ""), r"^[0-9a-f]{40}$")
        self.assertTrue(str(source.get("worktreePolicy") or "").strip())

        generator = self.manifest.get("generator") or {}
        self.assertEqual(generator.get("name"), "Archify")
        self.assertEqual(generator.get("version"), "2.16.0")
        self.assertEqual(generator.get("qualityProfile"), "showcase")

        policy = self.manifest.get("policy") or {}
        self.assertEqual(policy.get("navigation"), "new-tab-only")
        self.assertIs(policy.get("iframe"), False)
        self.assertIs(policy.get("liveData"), False)
        self.assertEqual(policy.get("httpExternalRequests"), "blocked-by-csp")
        self.assertIn("file://", str(policy.get("fileProtocolCaveat") or ""))

    def test_manifest_paths_hashes_validation_and_visual_gates(self):
        for artifact_id, (kind, spec_relative, html_relative) in EXPECTED_ARTIFACTS.items():
            with self.subTest(artifact=artifact_id):
                row = self.by_id[artifact_id]
                self.assertEqual(row.get("type"), kind)
                self.assertEqual(row.get("specPath"), spec_relative)
                self.assertEqual(row.get("htmlPath"), html_relative)
                spec_path = _contained_repo_file(row.get("specPath"))
                html_path = _contained_repo_file(row.get("htmlPath"))
                self.assertEqual(row.get("specSha256"), _sha256(spec_path))
                self.assertEqual(row.get("htmlSha256"), _sha256(html_path))
                self.assertNotIn(
                    b"\r\n",
                    spec_path.read_bytes(),
                    "Archify 規格檔必須維持 LF，否則 Windows checkout 會破壞清單雜湊",
                )
                self.assertNotIn(
                    b"\r\n",
                    html_path.read_bytes(),
                    "Archify HTML 必須維持 LF，否則跨平台逐位元組驗證不一致",
                )

                validation = row.get("validation") or {}
                self.assertEqual(validation.get("passed"), 9)
                self.assertEqual(validation.get("total"), 9)
                self.assertEqual(validation.get("errors"), 0)
                self.assertEqual(validation.get("warnings"), 0)

                visual = row.get("visual") or {}
                self.assertEqual(visual.get("status"), "passed")
                self.assertEqual(set(visual.get("viewportsPassed") or []), EXPECTED_VIEWPORTS)
                self.assertEqual(set(visual.get("themesPassed") or []), {"light", "dark"})

                network = row.get("network") or {}
                self.assertEqual(network.get("staticScan"), "passed")
                self.assertIs(network.get("cspEnforced"), True)

    def test_specs_are_showcase_static_sources_without_locale_override(self):
        for artifact_id, (kind, spec_relative, _html_relative) in EXPECTED_ARTIFACTS.items():
            with self.subTest(artifact=artifact_id):
                spec = _strict_json_file(ROOT / spec_relative)
                self.assertIsInstance(spec, dict)
                self.assertEqual(spec.get("diagram_type"), kind)
                self.assertIn(spec.get("schema_version"), {1, 2})
                meta = spec.get("meta") or {}
                self.assertEqual(meta.get("quality_profile"), "showcase")
                self.assertNotIn("locale", meta)

    def test_html_has_no_embed_runtime_api_or_active_external_resource(self):
        forbidden_api = re.compile(
            r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\s*\(",
            re.IGNORECASE,
        )
        forbidden_tags = {"iframe", "frame", "object", "embed", "form"}
        active_resource_tags = {"script", "img", "audio", "video", "source"}

        for artifact_id, (_kind, _spec_relative, html_relative) in EXPECTED_ARTIFACTS.items():
            with self.subTest(artifact=artifact_id):
                html_path = ROOT / html_relative
                text = html_path.read_text(encoding="utf-8")
                self.assertIn('<meta name="generator" content="archify 2.16.0">', text)
                self.assertIsNone(forbidden_api.search(text))

                parser = _ResourceParser()
                parser.feed(text)
                for tag, attrs in parser.tags:
                    self.assertNotIn(tag, forbidden_tags)
                    if tag in active_resource_tags:
                        source = attrs.get("src", "")
                        self.assertNotRegex(source, r"^https?://")
                    if tag == "link" and re.match(r"^https?://", attrs.get("href", "")):
                        host = re.sub(
                            r"^https?://([^/]+).*$",
                            r"\1",
                            attrs["href"],
                            flags=re.IGNORECASE,
                        ).lower()
                        self.assertIn(host, ALLOWED_EXTERNAL_LINK_HOSTS)

    def test_artifacts_do_not_contain_local_paths_credentials_or_receipts(self):
        files = [MANIFEST_PATH]
        for _artifact_id, (_kind, spec_relative, html_relative) in EXPECTED_ARTIFACTS.items():
            files.extend((ROOT / spec_relative, ROOT / html_relative))
        forbidden = (
            re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+"),
            re.compile(r"(?i)(?:^|[/\\])\.loop-engineering(?:[/\\]|$)"),
            re.compile(r"(?i)\b(?:sk|xox[baprs]|gh[opurs])-[A-Za-z0-9_-]{16,}"),
            re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        )
        for path in files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for pattern in forbidden:
                    self.assertIsNone(pattern.search(text), pattern.pattern)
                self.assertNotIn("visual-check", path.name.lower())
                self.assertNotIn("receipt", path.name.lower())


if __name__ == "__main__":
    unittest.main()
