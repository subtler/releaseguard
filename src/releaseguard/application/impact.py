"""Structure-aware Python change-impact analysis."""

import ast
from collections import defaultdict, deque
from pathlib import Path

from releaseguard.domain.models import ImpactAssessment, RepositorySnapshot
from releaseguard.ports.code_context import CodeContextPort


class PythonImpactAnalyzer:
    """Build a bounded static import graph from an immutable commit."""

    def __init__(
        self,
        source: CodeContextPort,
        *,
        max_files: int,
        max_file_bytes: int,
        max_depth: int = 3,
    ) -> None:
        self._source = source
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._max_depth = max_depth

    def analyze(self, repository: Path, snapshot: RepositorySnapshot) -> ImpactAssessment:
        """Return downstream modules and tests affected through static imports."""
        manifest = self._source.list_files(repository, snapshot.head_sha, max_files=self._max_files)
        python_paths = tuple(path for path in manifest.paths if path.endswith(".py"))
        modules_by_path = {
            path: module
            for path in python_paths
            if (module := self._module_for_path(path)) is not None
        }
        paths_by_module = {module: path for path, module in modules_by_path.items()}
        imports_by_module: dict[str, set[str]] = {}
        parse_failures: list[str] = []

        for path, module in modules_by_path.items():
            try:
                content = self._source.read_text_file(
                    repository,
                    snapshot.head_sha,
                    path,
                    max_bytes=self._max_file_bytes,
                )
                imports_by_module[module] = self._imports(content, module, path)
            except (RuntimeError, SyntaxError, ValueError):
                parse_failures.append(path)

        changed_modules = {
            module
            for item in snapshot.changed_files
            if (module := self._module_for_path(item.path)) is not None
        }
        reverse_graph = self._reverse_graph(imports_by_module, set(paths_by_module))
        direct_modules = {
            dependent
            for changed in changed_modules
            for dependent in reverse_graph.get(changed, set())
        } - changed_modules
        transitive_modules = self._transitive_dependents(
            changed_modules, reverse_graph, direct_modules
        )
        candidate_test_modules = {
            module
            for module in direct_modules | transitive_modules | changed_modules
            if self._is_test_path(paths_by_module.get(module, ""))
        }
        limitations = [
            "Static impact currently indexes Python imports only.",
            "Dynamic imports, reflection, runtime routing, and external services are not modeled.",
        ]
        if manifest.truncated:
            limitations.append("The repository manifest reached the configured file limit.")
        if parse_failures:
            limitations.append(
                "Some Python files could not be read or parsed within safety limits."
            )
        return ImpactAssessment(
            commit_sha=snapshot.head_sha,
            changed_modules=tuple(sorted(changed_modules)),
            direct_dependents=self._paths(direct_modules, paths_by_module),
            transitive_dependents=self._paths(transitive_modules, paths_by_module),
            candidate_tests=self._paths(candidate_test_modules, paths_by_module),
            indexed_file_count=len(modules_by_path),
            parse_failures=tuple(sorted(parse_failures)),
            limitations=tuple(limitations),
        )

    def _transitive_dependents(
        self,
        changed_modules: set[str],
        reverse_graph: dict[str, set[str]],
        direct_modules: set[str],
    ) -> set[str]:
        visited = set(changed_modules) | direct_modules
        transitive: set[str] = set()
        queue = deque((module, 1) for module in direct_modules)
        while queue:
            module, depth = queue.popleft()
            if depth >= self._max_depth:
                continue
            for dependent in reverse_graph.get(module, set()):
                if dependent in visited:
                    continue
                visited.add(dependent)
                transitive.add(dependent)
                queue.append((dependent, depth + 1))
        return transitive

    @staticmethod
    def _reverse_graph(
        imports_by_module: dict[str, set[str]], known_modules: set[str]
    ) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = defaultdict(set)
        for dependent, imported_names in imports_by_module.items():
            for imported in imported_names:
                matches = {
                    candidate
                    for candidate in known_modules
                    if imported == candidate or imported.startswith(f"{candidate}.")
                }
                if matches:
                    graph[max(matches, key=len)].add(dependent)
        return dict(graph)

    @staticmethod
    def _imports(content: str, module: str, path: str) -> set[str]:
        tree = ast.parse(content, filename=path)
        imported: set[str] = set()
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = PythonImpactAnalyzer._resolve_import_from(package, node.module, node.level)
                if base:
                    imported.add(base)
                    imported.update(f"{base}.{alias.name}" for alias in node.names)
        return imported

    @staticmethod
    def _resolve_import_from(package: str, imported_module: str | None, level: int) -> str:
        if level == 0:
            return imported_module or ""
        package_parts = package.split(".") if package else []
        keep = max(0, len(package_parts) - level + 1)
        prefix = package_parts[:keep]
        if imported_module:
            prefix.extend(imported_module.split("."))
        return ".".join(prefix)

    @staticmethod
    def _module_for_path(path: str) -> str | None:
        normalized = path.removeprefix("./")
        if not normalized.endswith(".py"):
            return None
        parts = normalized[:-3].split("/")
        if "src" in parts:
            parts = parts[parts.index("src") + 1 :]
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts or any(not part.isidentifier() for part in parts):
            return None
        return ".".join(parts)

    @staticmethod
    def _is_test_path(path: str) -> bool:
        name = path.rsplit("/", maxsplit=1)[-1]
        return path.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")

    @staticmethod
    def _paths(modules: set[str], paths_by_module: dict[str, str]) -> tuple[str, ...]:
        return tuple(
            sorted(paths_by_module[module] for module in modules if module in paths_by_module)
        )
