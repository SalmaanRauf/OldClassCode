"""
Regression tests for movement brief shell styling and component copy.
"""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_movement_brief_chainlit_configs_both_load_shell_css():
    root_config = (PROJECT_ROOT / ".chainlit" / "config.toml").read_text()
    app_config = (PROJECT_ROOT / "chainlit_app" / ".chainlit" / "config.toml").read_text()

    assert 'custom_css = "/public/movement-brief-shell.css"' in root_config
    assert 'custom_css = "/public/movement-brief-shell.css"' in app_config


def test_movement_brief_shell_avoids_viewport_width_overflow():
    shell_css = (PROJECT_ROOT / "public" / "movement-brief-shell.css").read_text()

    assert "100vw" not in shell_css
    assert "width: min(96rem, 100%)" in shell_css


def test_movement_brief_component_uses_internal_connections_and_current_projects_labels():
    component = (PROJECT_ROOT / "public" / "elements" / "MovementBrief.jsx").read_text()

    assert "Source marker" not in component
    assert "Internal connections" in component
    assert "Current Projects" in component
    assert "Focus move" in component
