"""Keep the book's learning checks attached to real tests, without executing them.

This checks references and bilingual command parity, not implementation behavior
or the correctness of prose. The referenced tests remain the behavioral oracles.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import shlex
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
BOOK = REPO / "docs" / "book"
PAGES = (BOOK / "chapters/12-control-plane-course.md",
         BOOK / "en/chapters/12-control-plane-course.md")
CHECKPOINTS = ("state", "lease", "settlement", "monitor")


def checkpoint_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    previous_end = -1
    for name in CHECKPOINTS:
        start = f"<!-- reader-checkpoint:{name}:start -->"
        end = f"<!-- reader-checkpoint:{name}:end -->"
        if markdown.count(start) != 1 or markdown.count(end) != 1:
            raise ValueError(f"{name}: expected one start and one end marker")
        start_at, end_at = markdown.index(start), markdown.index(end)
        if start_at <= previous_end or end_at < start_at:
            raise ValueError(f"{name}: checkpoint markers are out of order")
        sections[name] = markdown[start_at + len(start):end_at]
        previous_end = end_at + len(end)
    return sections


def pytest_nodes(section: str) -> tuple[str, ...]:
    nodes: list[str] = []
    for block in re.findall(r"(?ms)^```bash\n(.*?)^```[ \t]*$", section):
        argv = shlex.split(block.replace("\\\n", " "), comments=True)
        if "pytest" not in argv:
            continue
        nodes.extend(arg for arg in argv[argv.index("pytest") + 1:]
                     if arg.startswith("tests/"))
    if not nodes:
        raise ValueError("checkpoint has no pytest test selectors")
    return tuple(nodes)


def require_test_node(root: Path, node: str) -> None:
    """Resolve only the top-level test functions used by this short workbook."""
    match = re.fullmatch(r"(tests/[A-Za-z0-9_/-]+\.py)::(test_[A-Za-z0-9_]+)", node)
    if match is None:
        raise ValueError(f"unsupported test selector: {node}")
    source, symbol = match.groups()
    path = (root / source).resolve()
    if not path.is_relative_to((root / "tests").resolve()) or not path.is_file():
        raise ValueError(f"missing or out-of-scope test source: {source}")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=source)
    functions = {item.name for item in tree.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if symbol not in functions:
        raise ValueError(f"missing top-level test: {node}")


class ReaderCheckpointReferences(unittest.TestCase):
    def test_bilingual_checkpoint_commands_match(self) -> None:
        zh, en = (checkpoint_sections(page.read_text(encoding="utf-8")) for page in PAGES)
        for name in CHECKPOINTS:
            with self.subTest(checkpoint=name):
                self.assertEqual(pytest_nodes(zh[name]), pytest_nodes(en[name]))

    def test_each_documented_selector_resolves_in_current_checkout(self) -> None:
        for page in PAGES:
            for name, section in checkpoint_sections(page.read_text(encoding="utf-8")).items():
                for node in pytest_nodes(section):
                    with self.subTest(page=str(page), checkpoint=name, node=node):
                        require_test_node(REPO, node)


class ReaderCheckpointGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markdown = "\n".join(
            f"<!-- reader-checkpoint:{name}:start -->\n"
            "```bash\nuv run --extra test pytest -q \\\n"
            "  tests/test_example.py::test_example\n```\n"
            f"<!-- reader-checkpoint:{name}:end -->" for name in CHECKPOINTS
        )

    def test_multiline_command_selector(self) -> None:
        sections = checkpoint_sections(self.markdown)
        self.assertEqual(pytest_nodes(sections["state"]),
                         ("tests/test_example.py::test_example",))

    def test_missing_or_duplicate_marker_is_rejected(self) -> None:
        marker = "<!-- reader-checkpoint:state:start -->"
        for malformed in (self.markdown.replace(marker, ""), self.markdown + marker):
            with self.subTest(markdown=malformed):
                with self.assertRaisesRegex(ValueError, "one start and one end"):
                    checkpoint_sections(malformed)

    def test_reordered_checkpoints_are_rejected(self) -> None:
        malformed = (self.markdown.replace("checkpoint:state:", "checkpoint:temporary:")
                     .replace("checkpoint:lease:", "checkpoint:state:")
                     .replace("checkpoint:temporary:", "checkpoint:lease:"))
        with self.assertRaisesRegex(ValueError, "out of order"):
            checkpoint_sections(malformed)

    def test_no_test_command_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no pytest"):
            pytest_nodes("```text\ntests/test_example.py::test_example\n```\n")

    def test_test_body_is_not_imported_and_missing_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tests").mkdir()
            (root / "tests/test_example.py").write_text(
                "raise RuntimeError('must not import')\n\ndef test_example():\n    pass\n",
                encoding="utf-8",
            )
            require_test_node(root, "tests/test_example.py::test_example")
            with self.assertRaisesRegex(ValueError, "missing top-level"):
                require_test_node(root, "tests/test_example.py::test_renamed")
            with self.assertRaisesRegex(ValueError, "missing or out-of-scope"):
                require_test_node(root, "tests/test_missing.py::test_example")

    def test_unsupported_selector_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported test selector"):
            require_test_node(REPO, "tests/../private.py::test_example")


if __name__ == "__main__":
    unittest.main()
