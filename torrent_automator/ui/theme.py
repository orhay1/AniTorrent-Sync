"""Application stylesheet (dark and light) built from a small set of color tokens."""
from pathlib import Path

CHECK_ICON = (Path(__file__).parent / "assets" / "check.svg").as_posix()

DARK = {
    "bg": "#12141a",
    "surface": "#1b1e26",
    "surface2": "#232733",
    "border": "#2e3340",
    "text": "#e6e8ee",
    "muted": "#9097a6",
    "accent": "#3db4f2",       # AniList blue
    "accent_hover": "#5cc2f5",
    "accent_text": "#0b1117",
    "danger": "#e5534b",
    "warn": "#d9a440",
    "ok": "#4cc38a",
    "selection": "#2a4a63",
}

LIGHT = {
    "bg": "#eef1f6",
    "surface": "#ffffff",
    "surface2": "#f4f6fa",
    "border": "#d5dae3",
    "text": "#1d2330",
    "muted": "#5f6878",
    "accent": "#1a8fd0",
    "accent_hover": "#2aa0e0",
    "accent_text": "#ffffff",
    "danger": "#c93c37",
    "warn": "#a8730f",
    "ok": "#1f9d63",
    "selection": "#cfe6f5",
}

_current = dict(DARK)


def colors() -> dict:
    """Tokens of the theme currently applied (used by custom-painted widgets)."""
    return _current


def stylesheet(dark: bool = True) -> str:
    c = DARK if dark else LIGHT
    _current.clear()
    _current.update(c)
    return f"""
QWidget {{
    background: {c['bg']};
    color: {c['text']};
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
}}
QCheckBox::indicator, QRadioButton::indicator, QTreeView::indicator, QListView::indicator {{
    width: 15px; height: 15px;
}}
QCheckBox::indicator, QTreeView::indicator, QListView::indicator {{
    border: 1px solid {c['muted']}; border-radius: 4px; background: {c['surface2']};
}}
QRadioButton::indicator {{
    border: 1px solid {c['muted']}; border-radius: 8px; background: {c['surface2']};
}}
QRadioButton::indicator:checked {{
    border-color: {c['accent']};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {c['accent']}, stop:0.5 {c['accent']}, stop:0.6 {c['surface2']}, stop:1 {c['surface2']});
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']};
    image: url("{CHECK_ICON}");
}}
QMainWindow::separator {{ background: {c['border']}; width: 1px; height: 1px; }}
QToolTip {{
    background: {c['surface2']}; color: {c['text']};
    border: 1px solid {c['border']}; padding: 4px 6px;
}}
QMenuBar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {c['surface2']}; border-radius: 4px; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['selection']}; }}
QMenu::item:disabled {{ color: {c['muted']}; }}

QFrame#Card, QGroupBox {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
}}
QGroupBox {{ margin-top: 14px; padding: 14px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 4px;
    color: {c['muted']};
}}
QFrame#Card QLabel, QGroupBox QLabel, QFrame#Card QCheckBox, QGroupBox QCheckBox,
QGroupBox QRadioButton, QFrame#Card QWidget#Transparent, QGroupBox QWidget#Transparent {{
    background: transparent;
}}
QFrame#Header {{
    background: {c['surface']};
    border-bottom: 1px solid {c['border']};
}}
QFrame#Header QLabel {{ background: transparent; }}
QWidget#Transparent {{ background: transparent; }}
QScrollArea#GroupedGrid, QScrollArea#GroupedGrid > QWidget {{ background: transparent; border: none; }}
QLabel#GroupTitle {{ font-size: 11pt; font-weight: 700; }}
QLabel#AppTitle {{ font-size: 15pt; font-weight: 700; }}
QLabel#SectionTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Hint {{ color: {c['muted']}; font-size: 9pt; }}
QLabel#Warn {{ color: {c['warn']}; }}
QLabel#Chip {{
    background: {c['surface2']}; border: 1px solid {c['border']};
    border-radius: 10px; padding: 2px 9px;
}}
QLabel#ChipAccent {{
    background: {c['selection']}; border: 1px solid {c['accent']};
    border-radius: 10px; padding: 2px 9px;
}}

QPushButton {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['selection']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
QPushButton#Primary {{
    background: {c['accent']}; color: {c['accent_text']};
    border: 1px solid {c['accent']}; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['muted']}; }}
QPushButton#Danger {{ color: {c['danger']}; }}
QPushButton#Danger:hover {{ border-color: {c['danger']}; }}
QPushButton#Flat {{ background: transparent; border: none; color: {c['accent']}; padding: 4px 6px; }}
QPushButton#Flat:hover {{ text-decoration: underline; }}

QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['surface']}; border: 1px solid {c['border']};
    selection-background-color: {c['selection']}; selection-color: {c['text']};
}}

QListWidget, QTreeWidget {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{ border-radius: 6px; padding: 3px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c['surface2']}; }}
QListWidget#CoverGrid::item:selected, QListWidget#CoverGrid::item:hover {{ background: transparent; }}
QHeaderView::section {{
    background: {c['surface2']}; color: {c['muted']};
    border: none; border-bottom: 1px solid {c['border']}; padding: 5px 8px;
}}

QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {c['muted']};
    padding: 9px 18px; border: none; border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}

QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {c['surface']}; padding: 6px 10px;
    border-bottom: 1px solid {c['border']};
}}
QTextEdit#Log {{
    font-family: Consolas, "Cascadia Mono", monospace; font-size: 9pt;
    border-radius: 0; border: none; background: {c['surface']};
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QStatusBar QLabel {{ background: transparent; color: {c['muted']}; }}
QSplitter::handle {{ background: transparent; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QDialog {{ background: {c['bg']}; }}
"""
