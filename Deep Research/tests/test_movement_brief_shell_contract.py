"""
Regression tests for movement brief shell styling and component copy.
"""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_movement_brief_chainlit_configs_both_load_shell_css():
    root_config = (PROJECT_ROOT / ".chainlit" / "config.toml").read_text()
    app_config = (PROJECT_ROOT / "chainlit_app" / ".chainlit" / "config.toml").read_text()

    assert 'custom_css = "/public/movement-brief-shell.css?v=20260407a"' in root_config
    assert 'custom_css = "/public/movement-brief-shell.css?v=20260407a"' in app_config


def test_movement_brief_shell_avoids_viewport_width_overflow():
    shell_css = (PROJECT_ROOT / "public" / "movement-brief-shell.css").read_text()

    assert "100vw" not in shell_css
    assert "body:has(.movement-brief) main" in shell_css
    assert ".flex.flex-col.mx-auto.w-full.flex-grow.p-4:has(.movement-brief)" in shell_css
    assert ".step:has(.movement-brief) > div" in shell_css
    assert "[data-step-type=\"assistant_message\"]:has(.movement-brief) .ai-message" in shell_css
    assert "width: 100% !important;" in shell_css
    assert "max-width: none !important;" in shell_css


def test_movement_brief_component_uses_full_available_width():
    component = (PROJECT_ROOT / "public" / "elements" / "MovementBrief.jsx").read_text()

    assert "max-width: min(108rem, 100%)" not in component
    assert "max-width: none;" in component


def test_movement_brief_component_relaxes_desktop_table_min_width():
    component = (PROJECT_ROOT / "public" / "elements" / "MovementBrief.jsx").read_text()

    assert "min-width: 72rem" not in component
    assert "min-width: 64rem" not in component
    assert "min-width: 58rem" not in component
    assert "min-width: 0;" in component
    assert "table-layout: fixed;" in component


def test_movement_brief_component_uses_internal_connections_and_current_projects_labels():
    component = (PROJECT_ROOT / "public" / "elements" / "MovementBrief.jsx").read_text()

    assert "Source marker" not in component
    assert "Internal connections" in component
    assert "Current Projects" in component
    assert "Focus move" in component
