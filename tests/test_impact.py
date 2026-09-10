"""Structure-aware impact analysis tests."""

from pathlib import Path

from releaseguard.application.impact import PythonImpactAnalyzer
from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    RepositorySnapshot,
    SourceManifest,
)


class FakeSource:
    def __init__(self, files: dict[str, str], *, truncated: bool = False) -> None:
        self.files = files
        self.truncated = truncated

    def list_files(self, repository: Path, commit_sha: str, *, max_files: int) -> SourceManifest:
        del repository
        paths = tuple(self.files)[:max_files]
        return SourceManifest(
            commit_sha=commit_sha,
            paths=paths,
            truncated=self.truncated or len(self.files) > max_files,
        )

    def read_text_file(
        self,
        repository: Path,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
    ) -> str:
        del repository, commit_sha
        content = self.files[path]
        if len(content.encode()) > max_bytes:
            raise RuntimeError("bounded read failed")
        return content


def snapshot(*changed_paths: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=tuple(
            ChangedFile(path=path, status=ChangeStatus.MODIFIED) for path in changed_paths
        ),
        diff_text="",
    )


def test_python_impact_finds_direct_transitive_and_test_dependents() -> None:
    source = FakeSource(
        {
            "src/shop/models.py": "class Order: pass\n",
            "src/shop/service.py": "from shop.models import Order\n",
            "src/shop/api.py": "from shop.service import create_order\n",
            "tests/test_service.py": "from shop.service import create_order\n",
            "README.md": "ignored",
        }
    )
    analyzer = PythonImpactAnalyzer(source, max_files=100, max_file_bytes=10_000)

    impact = analyzer.analyze(Path("/safe/repository"), snapshot("src/shop/models.py"))

    assert impact.changed_modules == ("shop.models",)
    assert impact.direct_dependents == ("src/shop/service.py",)
    assert impact.transitive_dependents == ("src/shop/api.py", "tests/test_service.py")
    assert impact.candidate_tests == ("tests/test_service.py",)
    assert impact.indexed_file_count == 4


def test_python_impact_reports_bounded_manifest_and_parse_failures() -> None:
    source = FakeSource(
        {
            "src/shop/models.py": "class Order: pass\n",
            "src/shop/broken.py": "this is not valid python !!!",
        },
        truncated=True,
    )
    analyzer = PythonImpactAnalyzer(source, max_files=100, max_file_bytes=10_000)

    impact = analyzer.analyze(Path("/safe/repository"), snapshot("src/shop/models.py"))

    assert impact.parse_failures == ("src/shop/broken.py",)
    assert any("file limit" in limitation for limitation in impact.limitations)
    assert any("could not be read or parsed" in limitation for limitation in impact.limitations)


def test_python_module_mapping_rejects_non_python_and_invalid_paths() -> None:
    assert PythonImpactAnalyzer._module_for_path("src/shop/__init__.py") == "shop"
    assert PythonImpactAnalyzer._module_for_path("docs/guide.md") is None
    assert PythonImpactAnalyzer._module_for_path("src/bad-name.py") is None
