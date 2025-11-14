"""Dependency availability regression tests."""

from pathlib import Path
import tomllib


def test_pyproject_lists_itsdangerous() -> None:
    """Guard the rite: ensure itsdangerous is declared as a dependency."""

    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    data = tomllib.loads(content)

    dependencies = data["project"]["dependencies"]
    assert any(
        dep.startswith("itsdangerous") for dep in dependencies
    ), "itsdangerous must be listed under project dependencies."


def test_pyproject_lists_email_validator() -> None:
    """Guard the rite: ensure email-validator is declared as a dependency."""

    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    data = tomllib.loads(content)

    dependencies = data["project"]["dependencies"]
    assert any(
        dep.startswith("email-validator") for dep in dependencies
    ), "email-validator must be listed under project dependencies."


def test_pyproject_pins_compatible_bcrypt() -> None:
    """Ensure bcrypt version stays compatible with passlib detection."""

    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    data = tomllib.loads(content)

    dependencies = data["project"]["dependencies"]
    assert any(
        dep.startswith("bcrypt<4") for dep in dependencies
    ), "bcrypt must be pinned below 4.0 for passlib compatibility."


def test_google_genai_import() -> None:
    """Guard the rite: ensure google-genai can be imported correctly."""

    try:
        from google import genai
        from google.genai import types
        assert genai is not None
        assert types is not None
    except ImportError as e:
        raise AssertionError(
            f"google-genai import failed: {e}. "
            "Ensure google-genai>=1.43.0 is installed."
        ) from e

