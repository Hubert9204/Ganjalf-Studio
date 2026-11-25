"""Ganjalf: upstream tests that pin Unsloth's own README (Docker quick start, dev install).

The Ganjalf README documents the Ganjalf launcher instead and links to Unsloth's install and
Docker guides, so these checks do not apply to it. Listed here, not edited in each test, so an
upstream merge does not conflict; they still run against an Unsloth README.
"""

from pathlib import Path

import pytest

UPSTREAM_README_TESTS = frozenset(
    {
        "test_installer_elevation_report.py::test_the_readme_dev_studio_home_is_ignored_by_git",
        "test_docker_hub_readme.py::test_the_hub_readme_explains_the_studio_volume",
        "test_docker_hub_readme.py::test_every_studio_run_keeps_the_studio_volume",
        "test_docker_hub_readme.py::test_the_repo_readme_run_command_matches_the_image",
        "test_docker_studio_home_volume.py::test_the_docs_mount_the_studio_home",
        "test_docker_nvidia_toolkit_install.py::test_the_docs_point_at_the_installer",
        "test_docker_rocm.py::test_the_readme_no_longer_says_native_linux_only",
    }
)


def _ganjalf_readme(root: Path) -> bool:
    try:
        return "Ganjalf Studio" in (root / "README.md").read_text(encoding = "utf-8")
    except OSError:
        return False


def skip_upstream_readme_tests(config, items) -> None:
    if not _ganjalf_readme(Path(str(config.rootpath))):
        return
    marker = pytest.mark.skip(
        reason = "pins Unsloth's README; Ganjalf's README documents its own launcher"
    )
    for item in items:
        key = f"{Path(str(item.path)).name}::{item.originalname if hasattr(item, 'originalname') else item.name}"
        if key in UPSTREAM_README_TESTS:
            item.add_marker(marker)
