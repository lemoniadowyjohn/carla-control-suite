"""Small composable UI elements; no simulator dependencies."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)


def text_label(text: str, role: str = "muted", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(role)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def card(title: str, value: str, detail: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 13, 16, 13)
    layout.addWidget(text_label(title.upper(), "card-caption"))
    layout.addWidget(text_label(value, "card-number"))
    if detail:
        layout.addWidget(text_label(detail, "muted"))
    return frame


def section(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(11)
    layout.setContentsMargins(15, 16, 15, 16)
    layout.addWidget(text_label(title, "workspace-heading"))
    if subtitle:
        layout.addWidget(text_label(subtitle, "section-subtitle"))
    return widget, layout


def line(*widgets: QWidget) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    for item in widgets:
        layout.addWidget(item)
    return widget


def scroll_page(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll


def action(name: str, func, primary: bool = False) -> QPushButton:
    button = QPushButton(name)
    button.setAccessibleName(name)
    button.clicked.connect(func)
    if primary:
        button.setObjectName("primary-action")
    return button
