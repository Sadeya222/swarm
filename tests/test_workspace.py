import tempfile
import unittest
from pathlib import Path

from swarm.workspace import ProjectScaffolder, Workspace, WorkspaceError


class WorkspaceTests(unittest.TestCase):
    def test_scaffold_has_explicit_project_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = ProjectScaffolder.create(directory, "weather-tool")
            self.assertTrue((path / "pyproject.toml").exists())
            self.assertTrue((path / "src" / "weather_tool" / "main.py").exists())
            self.assertTrue((path / "tests" / "test_smoke.py").exists())
            self.assertTrue((path / ".vscode" / "settings.json").exists())

    def test_workspace_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkspaceError):
                Workspace(directory).inside(Path("..") / "outside.txt")


if __name__ == "__main__":
    unittest.main()
