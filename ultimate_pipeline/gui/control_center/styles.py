"""Single dark visual system for the CARLA Ops Studio operator console."""

CONTROL_CENTRE_QSS = """
QMainWindow, QWidget#central { background: #0c121d; color: #e8eef8; }
QWidget { font-family: 'Segoe UI', 'Arial'; font-size: 12px; }
QWidget#sidebar { background: #101a2a; border-right: 1px solid #263347; }
QWidget#topbar, QWidget#status-strip { background: #121e30; }
QFrame#card, QFrame#panel { background: #172337; border: 1px solid #2a3c53;
 border-radius: 9px; }
QLabel#app-brand { color: #f0f6ff; font-size: 19px; font-weight: 800; }
QLabel#workspace-heading { color: #f1f6ff; font-size: 22px; font-weight: 750; }
QLabel#card-caption, QLabel#muted, QLabel#section-subtitle { color: #a3b3cc; }
QLabel#card-number { color: #fafcff; font-size: 19px; font-weight: 700; }
QLabel#status-pill { background: #293b55; border-radius: 5px; padding: 5px 9px;
 color: #c6d6eb; font-weight: 650; }
QLabel#warning-pill { background: #48371f; border-radius: 5px; padding: 5px 9px;
 color: #ffd28d; font-weight: 650; }
QListWidget#nav-list { background: transparent; color: #c1cee1; border: 0;
 outline: none; font-size: 12px; }
QListWidget#nav-list::item { padding: 11px 12px; border-radius: 7px; margin: 2px 7px; }
QListWidget#nav-list::item:selected { background: #234b75; color: #ffffff; }
QListWidget#nav-list::item:hover { background: #263953; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QTableWidget, QTreeWidget, QListWidget:not(#nav-list) { background: #111b2b;
 border: 1px solid #34465e; color: #eaf1fa; border-radius: 5px;
 padding: 6px; selection-background-color: #295a8b; }
QPushButton { background: #263b55; border: 1px solid #3d5672; color: #f0f4fb;
 padding: 8px 12px; border-radius: 6px; font-weight: 600; }
QPushButton:hover { background: #315578; }
QPushButton:pressed { background: #1e4060; }
QPushButton:disabled { background: #1b2737; color: #7e90a7; border-color: #2b394b; }
QPushButton#primary-action { background: #196db1; border-color: #3489cd; }
QPushButton#primary-action:hover { background: #2586d1; }
QTabWidget::pane { border: 1px solid #2a3c53; background: #111b2b;
 border-radius: 6px; top: -1px; }
QTabBar::tab { background: #19273a; color: #abc0d8; padding: 11px 18px;
 margin-right: 3px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #294d73; color: #ffffff; }
QHeaderView::section { background: #23354d; color: #dce8f9;
 padding: 8px; border: none; border-right: 1px solid #31465c; }
QTableWidget { gridline-color: #2d3e54; }
QStatusBar { background: #0f1929; color: #a8bbd4; }
QScrollBar:vertical { background: #142033; width: 10px; }
QScrollBar::handle:vertical { background: #426080; border-radius: 4px; }
QSplitter::handle { background: #2b3e55; }
"""
