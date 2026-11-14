from pathlib import Path


def test_readme_describes_the_fixture():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "in-memory inventory" in readme
