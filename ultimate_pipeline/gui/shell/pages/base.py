"""Shared page scaffolding.

Every screen uses the same status vocabulary so an empty / loading / error /
disabled state looks and reads the same everywhere. That behaviour comes from
the spec: *Empty*, *Blocked*, *Error* and *Stale* each carry a specific,
actionable presentation rather than a blank panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ultimate_pipeline.gui.results import Result
from ultimate_pipeline.gui.shell.navigation import ControlBinding, ScreenRoute, route_for
from ultimate_pipeline.gui.shell.services import ServiceRegistry

__all__ = ["StatusPanel", "ControlRow", "BasePage", "PageState"]


class PageState(str):
    IDLE = "IDLE"
    LOADING = "LOADING"
    EMPTY = "EMPTY"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    STALE = "STALE"


@dataclass
class StatusPanel:
    """The mandated presentation for empty / blocked / error / stale."""

    state: str = PageState.IDLE
    message: str = ""
    detail: str = ""
    remediation: str = ""
    as_of: str = ""
    evidence_state: str = ""

    def as_dict(self) -> dict:
        return {"state": self.state, "message": self.message, "detail": self.detail,
                "remediation": self.remediation, "as_of": self.as_of,
                "evidence_state": self.evidence_state}


class ControlRow(QWidget):
    """A label, a status, and -- when available -- an action button.

    The row is genuinely DISABLED (not merely annotated) whenever the control
    is unavailable or the session authority forbids mutation. An enabled control
    must have a real backend action behind it.
    """

    def __init__(self, binding: ControlBinding, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.binding = binding
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.label = QLabel(binding.label)
        self.label.setObjectName(f"control-label-{binding.control_id}")
        self.label.setAccessibleName(binding.accessible_name)
        layout.addWidget(self.label)

        self.action = QLabel(binding.action)
        self.action.setObjectName(f"control-action-{binding.control_id}")
        self.action.setAccessibleName(f"{binding.accessible_name} action")
        self.action.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.action)

        self.status = QLabel()
        self.status.setObjectName(f"control-status-{binding.control_id}")
        self.status.setAccessibleName(f"{binding.accessible_name} status")
        layout.addWidget(self.status)

        self.test_id = QLabel(binding.test_id)
        self.test_id.setObjectName(f"control-test-{binding.control_id}")
        self.test_id.setAccessibleName(f"{binding.accessible_name} test id")
        layout.addWidget(self.test_id)

        self.apply_state()

    @property
    def enabled_for_use(self) -> bool:
        """True only when bound AND permitted by the session authority."""
        return self.binding.available and self.binding.mutation_allowed

    def apply_state(self) -> None:
        binding = self.binding
        if not binding.available:
            self.setEnabled(False)
            self.status.setText(f"DISABLED — {binding.disabled_reason}")
            self.status.setAccessibleName(f"{binding.accessible_name} disabled")
        elif not binding.mutation_allowed:
            # available backend, but the authority forbids mutating now
            self.setEnabled(False)
            self.status.setText(
                f"DISABLED BY AUTHORITY — {binding.authority_reason}")
            self.status.setAccessibleName(
                f"{binding.accessible_name} disabled by authority")
        else:
            self.setEnabled(True)
            self.status.setText(f"AVAILABLE — {binding.backend_service}")
            self.status.setAccessibleName(f"{binding.accessible_name} available")
        self.status.setProperty("control_available", binding.available)
        self.status.setProperty("control_enabled", self.enabled_for_use)


class BasePage(QWidget):
    """Common shell for the read-mostly screens."""

    route_key: str = ""

    def __init__(self, registry: ServiceRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.route: ScreenRoute = route_for(self.route_key) if self.route_key else None
        self.status_panel = StatusPanel()
        self.controls: list[ControlRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title = QLabel(self.route.title if self.route else self.route_key)
        self.title.setObjectName("page-title")
        self.title.setAccessibleName(f"{self.route_key} page title")
        self.title.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        layout.addWidget(self.title)

        self.container = QWidget()
        self.container.setObjectName("content-area")
        self.container.setAccessibleName(f"{self.route_key} content")
        self.container_layout = QVBoxLayout(self.container)
        layout.addWidget(self.container)

        self.state_line = QLabel("")
        self.state_line.setObjectName("page-state")
        self.state_line.setAccessibleName(f"{self.route_key} status")
        layout.addWidget(self.state_line)

    # -- helpers -----------------------------------------------------------
    def add_control(self, binding: ControlBinding) -> ControlRow:
        row = ControlRow(binding, self.container)
        self.container_layout.addWidget(row)
        self.controls.append(row)
        return row

    def clear_dynamic_rows(self) -> None:
        """Remove previously generated rows so a refresh cannot grow the page.

        A long-lived window that refreshes must not accumulate duplicate
        controls, which would also corrupt any reconciliation that counts them.
        """
        for row in list(self.controls):
            self.container_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.controls.clear()

    def show_state(self, state: str, message: str = "", detail: str = "",
                   remediation: str = "", as_of: str = "",
                   evidence_state: str = "") -> None:
        """Render one of the mandated states with its remediation."""
        self.status_panel = StatusPanel(state, message, detail, remediation,
                                        as_of, evidence_state)
        parts = [state]
        if message:
            parts.append(message)
        if detail:
            parts.append(f"detail: {detail}")
        if remediation:
            parts.append(f"next: {remediation}")
        if as_of:
            parts.append(f"AS OF {as_of}")
        if evidence_state:
            parts.append(f"EVIDENCE: {evidence_state}")
        self.state_line.setText(" | ".join(parts))

    def show_result(self, result: Result, *, ok_message: str = "") -> None:
        if result.ok:
            self.show_state(PageState.IDLE, ok_message or "loaded")
        elif result.error_class == "BlockedExternal":
            self.show_state(PageState.BLOCKED, result.reason,
                            remediation=result.remediation)
        else:
            self.show_state(PageState.ERROR,
                            f"{result.error_class or 'Error'}: {result.reason}",
                            result.error_source, result.remediation)

    def control_ids(self) -> list[str]:
        return [row.binding.control_id for row in self.controls]

    def unavailable_controls(self) -> list[ControlBinding]:
        return [row.binding for row in self.controls if not row.binding.available]