"""Portable theme + stylesheet, lifted verbatim from the Fantastic Upgraded
Captioning Kit so a second app matches it exactly.

Drop this file into your project and call:

    from theme import Theme, build_stylesheet
    app.setStyleSheet(build_stylesheet(accent="#2f6fed"))

Only the accent is meant to be user-editable; every other token is fixed so
the palette stays coherent. Requires PySide6 only.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() * t + b.red() * (1 - t)),
        round(a.green() * t + b.green() * (1 - t)),
        round(a.blue() * t + b.blue() * (1 - t)),
    )


class Theme:
    """Resolved dark-theme palette. Fixed token roles + a derived accent ramp.

    Only the accent (and fonts) are user-editable; everything else is fixed so the
    theme stays coherent. Phase-1 token source of truth — QSS and the few painted
    widgets both read from here.
    """

    surface_0 = "#0F1115"
    surface_1 = "#171A1F"
    surface_2 = "#1E2227"
    surface_3 = "#262B31"
    surface_hover = "#2E343B"
    border = "#2A2F37"
    border_strong = "#373D46"
    border_strong_hover = "#454C56"
    text_primary = "#ECEEF1"
    text_secondary = "#A6ADB6"
    text_muted = "#6C737C"
    text_disabled = "#4A5158"
    success = "#45B964"
    warning = "#E0A33B"
    error = "#E5594B"
    tooltip_bg = "#22262C"
    tooltip_text = "#C9CFD7"

    def __init__(self, accent: str = "#2f6fed") -> None:
        base = QColor(accent) if accent else QColor("#2f6fed")
        if not base.isValid():
            base = QColor("#2f6fed")
        self.accent = base.name()
        self.accent_hover = base.lighter(118).name()
        self.accent_pressed = base.darker(115).name()
        self.accent_on_subtle = base.lighter(140).name()
        self.accent_subtle = _mix(base, QColor(self.surface_0), 0.18).name()
        self.accent_subtle_border = _mix(base, QColor(self.surface_0), 0.42).name()


def build_stylesheet(accent: str = "#2f6fed") -> str:
    """Dark QSS theme built from the token palette. Applies live (no restart)."""
    t = Theme(accent)
    # Spin-button arrows are images: Qt gives sub-controls no way to draw a shape,
    # and the CSS border-triangle fallback renders as blocks in this theme.
    up_arrow = lucide_arrow_url("chevron-up", t.text_secondary)
    down_arrow = lucide_arrow_url("chevron-down", t.text_secondary)
    up_arrow_hi = lucide_arrow_url("chevron-up", t.text_primary)
    down_arrow_hi = lucide_arrow_url("chevron-down", t.text_primary)
    up_arrow_off = lucide_arrow_url("chevron-up", t.border)
    down_arrow_off = lucide_arrow_url("chevron-down", t.border)
    return f"""
    QWidget {{ background: {t.surface_0}; color: {t.text_primary}; }}
    QMainWindow, QDialog {{ background: {t.surface_0}; }}
    QToolBar {{ background: {t.surface_1}; border: none; padding: 6px; spacing: 6px; }}
    QToolBar QToolButton {{ color: {t.text_secondary}; padding: 6px 10px; border-radius: 6px; background: transparent; border: none; }}
    QToolBar QToolButton:hover {{ background: {t.surface_hover}; color: {t.text_primary}; }}
    QToolBar QToolButton:checked {{ background: {t.accent}; color: #FFFFFF; }}
    QSplitter::handle {{ background: {t.border}; }}
    #Panel {{ background: {t.surface_1}; }}
    #Stage {{ background: {t.surface_0}; }}
    QStatusBar {{ background: {t.surface_1}; color: {t.text_secondary}; }}
    QStatusBar::item {{ border: none; }}
    QLabel {{ background: transparent; color: {t.text_primary}; }}
    QLabel#Hint {{ color: {t.text_muted}; }}
    QLabel#FieldHead {{ color: #0f848a; font-weight: 500; }}
    #PanelDivider {{ border: none; background: {t.border}; max-height: 1px; min-height: 1px; margin: 6px 0; }}
    QLabel#SectionLabel {{ color: {t.text_primary}; font-weight: 600; }}
    QLabel#CountStatus {{ color: {t.text_secondary}; }}

    QPushButton {{ background: {t.surface_3}; color: {t.text_primary}; border: 1px solid {t.border_strong}; border-radius: 6px; padding: 6px 14px; font-weight: 500; }}
    QPushButton:hover {{ background: {t.surface_hover}; border-color: {t.border_strong_hover}; }}
    QPushButton:pressed {{ background: {t.surface_1}; }}
    QPushButton:disabled {{ background: {t.surface_2}; border-color: {t.border}; color: {t.text_disabled}; }}
    QPushButton#Primary {{ background: {t.accent}; color: #FFFFFF; border: none; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {t.accent_hover}; }}
    QPushButton#Primary:pressed {{ background: {t.accent_pressed}; color: #DCE8FF; }}
    QPushButton#Primary:disabled {{ background: {t.surface_2}; color: {t.text_disabled}; }}
    QPushButton#Danger {{ background: transparent; border: 1px solid #4A3437; color: {t.error}; }}
    QPushButton#Danger:hover {{ background: rgba(229,89,75,0.12); }}

    QToolButton {{ background: {t.surface_2}; color: {t.text_secondary}; border: 1px solid {t.border}; border-radius: 6px; padding: 4px; }}
    QToolButton:hover {{ background: {t.surface_hover}; border-color: {t.border_strong_hover}; color: {t.text_primary}; }}
    QToolButton:checked {{ background: {t.accent}; color: #FFFFFF; border-color: {t.accent}; }}
    /* Checkable QPushButtons (Snap, Crop, Mute section) had no checked state at
       all, so they looked identical on and off. */
    QPushButton:checked {{ background: {t.accent}; color: #FFFFFF; border-color: {t.accent}; }}
    QPushButton:checked:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}

    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t.surface_2}; color: {t.text_primary};
        border: 1px solid {t.border_strong}; border-radius: 6px; padding: 5px 10px;
        selection-background-color: {t.accent_subtle}; selection-color: {t.text_primary};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}

    /* Giving QSpinBox a border and background drops Qt's native step buttons, and
       the fallback arrows render blank on a dark surface. Draw them with the CSS
       triangle trick so every spinbox in the app has visible steppers. */
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 18px; border-left: 1px solid {t.border};
        border-top-right-radius: 6px; background: {t.surface_2};
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 18px; border-left: 1px solid {t.border};
        border-bottom-right-radius: 6px; background: {t.surface_2};
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {t.surface_hover};
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url({up_arrow}); width: 11px; height: 11px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url({down_arrow}); width: 11px; height: 11px;
    }}
    QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {{ image: url({up_arrow_hi}); }}
    QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {{ image: url({down_arrow_hi}); }}
    QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{ image: url({up_arrow_off}); }}
    QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: url({down_arrow_off}); }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{ background: {t.surface_1}; border-color: {t.border}; color: {t.text_disabled}; }}
    QComboBox QAbstractItemView {{ background: {t.surface_2}; color: {t.text_primary}; border: 1px solid {t.border_strong}; selection-background-color: {t.accent_subtle}; selection-color: {t.text_primary}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}

    QCheckBox {{ background: transparent; color: {t.text_primary}; spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {t.border_strong}; border-radius: 4px; background: {t.surface_2}; }}
    QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
    QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}

    QRadioButton {{ background: transparent; color: {t.text_primary}; spacing: 8px; }}
    QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {t.border_strong}; border-radius: 9px; background: {t.surface_2}; }}
    QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
    QRadioButton::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}

    QTabWidget::pane {{ border: none; background: {t.surface_1}; }}
    QTabBar::tab {{ background: transparent; color: {t.text_muted}; padding: 6px 14px; border: none; border-radius: 4px; margin: 2px; }}
    QTabBar::tab:selected {{ background: {t.surface_3}; color: {t.text_primary}; }}
    QTabBar::tab:hover:!selected {{ color: {t.text_secondary}; }}

    QListWidget {{ background: {t.surface_1}; border: none; }}
    QListWidget::item {{ padding: 3px 4px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {t.accent_subtle}; color: {t.text_primary}; }}
    QScrollArea {{ background: transparent; border: none; }}

    #GuidanceBox {{ background: {t.surface_2}; color: {t.text_primary}; border: 1px solid {t.border_strong}; border-radius: 6px; }}
    #GuidanceBoxRO {{ background: {t.surface_1}; color: {t.text_secondary}; border: 1px solid {t.border}; border-radius: 6px; }}
    #ElementRow {{ background: {t.surface_2}; border: 1px solid {t.border}; border-radius: 6px; }}
    #TypePill {{ background: {t.surface_3}; color: {t.text_secondary}; border-radius: 7px; padding: 1px 0; font-size: 10px; }}
    #ElementRow QToolButton {{ background: transparent; border: none; color: {t.text_secondary}; font-size: 11px; }}
    #ElementRow QToolButton:hover {{ color: {t.text_primary}; }}
    #ExpandBtn {{ background: transparent; border: 1px solid {t.border_strong}; border-radius: 4px; }}
    #ExpandBtn:hover {{ border-color: {t.accent}; }}

    #CustomPill {{ background: {t.accent_subtle}; border: 1px solid {t.accent_subtle_border}; border-radius: 13px; }}
    #GrayPill {{ background: {t.surface_2}; border: 1px solid {t.border_strong}; border-radius: 13px; }}
    #PillText {{ background: transparent; border: none; color: {t.text_primary}; padding: 3px 8px; }}
    #PillText:hover {{ color: {t.accent_on_subtle}; }}
    #PillX {{ background: transparent; border: none; color: {t.text_muted}; padding-right: 4px; }}
    #PillX:hover {{ color: {t.error}; }}
    #TriggerDel {{ background: {t.surface_3}; border: 1px solid {t.border_strong}; border-radius: 7px; color: {t.text_secondary}; font-weight: 700; padding: 0; }}
    #TriggerDel:hover {{ background: {t.error}; border-color: {t.error}; color: #FFFFFF; }}
    #UsedPill {{ background: {t.accent_subtle}; border: 1px solid {t.accent_subtle_border}; border-radius: 12px; color: {t.accent_on_subtle}; padding: 3px 10px; }}

    #Rail {{ background: {t.surface_1}; border-right: 1px solid {t.border}; }}
    #RailButton {{ background: transparent; border: none; border-radius: 8px; }}
    #RailButton:hover {{ background: {t.surface_hover}; }}
    #RailButton:checked {{ background: {t.accent_subtle}; }}
    #TopBar {{ background: {t.surface_1}; border-bottom: 1px solid {t.border}; }}
    #TitleLabel {{ color: {t.text_secondary}; }}
    #ToolStrip {{ background: {t.surface_2}; border: 1px solid {t.border_strong}; border-radius: 12px; }}
    #ToolStrip QToolButton {{ background: transparent; border: none; border-radius: 8px; }}
    #ToolStrip QToolButton:hover {{ background: {t.surface_hover}; }}
    #ToolStrip QToolButton:checked {{ background: {t.accent_subtle}; }}
    #NavBar {{ background: {t.surface_1}; border-top: 1px solid {t.border}; }}
    #NavPill {{ background: {t.surface_2}; border: 1px solid {t.border_strong}; border-radius: 14px; }}
    #NavPill QToolButton#NavBtn {{ background: transparent; border: none; border-radius: 10px; padding: 2px; }}
    #NavPill QToolButton#NavBtn:hover {{ background: {t.surface_hover}; }}
    #NavCount {{ color: {t.text_secondary}; }}
    #JsonTab {{ background: {t.surface_1}; border-left: 1px solid {t.border}; }}
    #JsonTab:hover {{ background: {t.surface_hover}; }}
    #JsonSlideOver {{ background: {t.surface_1}; border-left: 1px solid {t.border_strong}; }}
    #PanelGhost {{ background: transparent; border: none; }}
    #CollapseChevron {{ background: transparent; border: none; border-radius: 6px; padding: 2px; }}
    #CollapseChevron:hover {{ background: {t.surface_hover}; }}

    QToolTip {{ background: {t.tooltip_bg}; color: {t.tooltip_text}; border: 1px solid {t.border_strong_hover}; border-radius: 6px; padding: 6px 10px; }}
    QProgressBar {{ background: {t.surface_2}; border: none; border-radius: 6px; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 6px; }}

    QScrollBar:horizontal {{ height: 12px; background: {t.surface_0}; margin: 0; border: none; }}
    QScrollBar:vertical {{ width: 12px; background: {t.surface_0}; margin: 0; border: none; }}
    QScrollBar::handle:horizontal {{ background: {t.accent}; min-width: 28px; border-radius: 5px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.accent}; min-height: 28px; border-radius: 5px; margin: 2px; }}
    QScrollBar::handle:hover {{ background: {t.accent_hover}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    """




_LUCIDE_ICONS = {
    "braces": "<path d='M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1' /> <path d='M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1' />",
    "check": "<path d='M20 6 9 17l-5-5' />",
    "chevron-down": "<path d='m6 9 6 6 6-6' />",
    "chevron-left": "<path d='m15 18-6-6 6-6' />",
    "chevron-right": "<path d='m9 18 6-6-6-6' />",
    "chevron-up": "<path d='m18 15-6-6-6 6' />",
    "chevrons-left": "<path d='m11 17-5-5 5-5' /> <path d='m18 17-5-5 5-5' />",
    "crop": "<path d='M6 2v14a2 2 0 0 0 2 2h14' /> <path d='M18 22V8a2 2 0 0 0-2-2H2' />",
    "link": ("<path d='M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71' />"
             " <path d='M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71' />"),
    "mouse-pointer": ("<path d='M12.586 12.586 19 19' />"
                      " <path d='M3.688 3.037a.497.497 0 0 0-.651.651l6.5 15.999a.501.501"
                      " 0 0 0 .947-.062l1.569-6.083a2 2 0 0 1 1.448-1.479l6.124-1.579a.5.5"
                      " 0 0 0 .063-.947z' />"),
    "hand": ("<path d='M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2' />"
             " <path d='M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2' />"
             " <path d='M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8' />"
             " <path d='M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34"
             "l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15' />"),
    "copy": ("<rect width='14' height='14' x='8' y='8' rx='2' ry='2' />"
             " <path d='M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2' />"),
    "image-plus": ("<path d='M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7' />"
                   " <path d='M16 5h6' /> <path d='M19 2v6' />"
                   " <circle cx='9' cy='9' r='2' />"
                   " <path d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21' />"),
    "eye-off": ("<path d='M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68' />"
                " <path d='M6.61 6.61A13.5 13.5 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61' />"
                " <path d='M14.12 14.12a3 3 0 1 1-4.24-4.24' /> <path d='m2 2 20 20' />"),
    "rotate-cw": ("<path d='M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8' />"
                  " <path d='M21 3v5h-5' />"),
    "rotate-ccw": ("<path d='M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8' />"
                   " <path d='M3 3v5h5' />"),
    "ellipsis": "<circle cx='12' cy='12' r='1' /> <circle cx='19' cy='12' r='1' /> <circle cx='5' cy='12' r='1' />",
    "film": "<rect width='18' height='18' x='3' y='3' rx='2' /> <path d='M7 3v18' /> <path d='M17 3v18' /> <path d='M3 7.5h4' /> <path d='M3 12h18' /> <path d='M3 16.5h4' /> <path d='M17 7.5h4' /> <path d='M17 16.5h4' />",
    "flag": "<path d='M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z' /> <path d='M4 22v-7' />",
    "folder-open": "<path d='m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2' />",
    "info": "<circle cx='12' cy='12' r='10' /> <path d='M12 16v-4' /> <path d='M12 8h.01' />",
    "lock": "<rect width='18' height='11' x='3' y='11' rx='2' ry='2' /> <path d='M7 11V7a5 5 0 0 1 10 0v4' />",
    "lock-open": "<rect width='18' height='11' x='3' y='11' rx='2' ry='2' /> <path d='M7 11V7a5 5 0 0 1 9.9-1' />",
    "maximize": "<path d='M8 3H5a2 2 0 0 0-2 2v3' /> <path d='M21 8V5a2 2 0 0 0-2-2h-3' /> <path d='M3 16v3a2 2 0 0 0 2 2h3' /> <path d='M16 21h3a2 2 0 0 0 2-2v-3' />",
    "maximize-2": "<path d='M15 3h6v6' /> <path d='m21 3-7 7' /> <path d='m3 21 7-7' /> <path d='M9 21H3v-6' />",
    "pause": "<rect x='14' y='4' width='4' height='16' rx='1' /> <rect x='6' y='4' width='4' height='16' rx='1' />",
    "play": "<path fill='{color}' d='M6 3.5v17a1 1 0 0 0 1.5.86l13-8.5a1 1 0 0 0 0-1.72l-13-8.5A1 1 0 0 0 6 3.5z' />",
    "volume-2": "<path d='M11 4.7a.7.7 0 0 0-1.2-.5L6 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2l3.8 3.8a.7.7 0 0 0 1.2-.5z' /> <path d='M16 9a5 5 0 0 1 0 6' /> <path d='M19.4 6.6a9 9 0 0 1 0 10.8' />",
    "volume-x": "<path d='M11 4.7a.7.7 0 0 0-1.2-.5L6 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2l3.8 3.8a.7.7 0 0 0 1.2-.5z' /> <line x1='22' x2='16' y1='9' y2='15' /> <line x1='16' x2='22' y1='9' y2='15' />",
    "mouse-pointer-2": "<path d='M4.037 4.688a.495.495 0 0 1 .651-.651l16 6.5a.5.5 0 0 1-.063.947l-6.124 1.58a2 2 0 0 0-1.438 1.435l-1.579 6.126a.5.5 0 0 1-.947.063z' />",
    "move": "<path d='M12 2v20' /> <path d='m15 19-3 3-3-3' /> <path d='m19 9 3 3-3 3' /> <path d='M2 12h20' /> <path d='m5 9-3 3 3 3' /> <path d='m9 5 3-3 3 3' />",
    "panel-left-close": "<rect width='18' height='18' x='3' y='3' rx='2' /> <path d='M9 3v18' /> <path d='m16 15-3-3 3-3' />",
    "panel-left-open": "<rect width='18' height='18' x='3' y='3' rx='2' /> <path d='M9 3v18' /> <path d='m14 9 3 3-3 3' />",
    "panel-right-close": "<rect width='18' height='18' x='3' y='3' rx='2' /> <path d='M15 3v18' /> <path d='m8 9 3 3-3 3' />",
    "panel-right-open": "<rect width='18' height='18' x='3' y='3' rx='2' /> <path d='M15 3v18' /> <path d='m10 15-3-3 3-3' />",
    "pencil": "<path d='M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z' /> <path d='m15 5 4 4' />",
    "plus": "<path d='M5 12h14' /> <path d='M12 5v14' />",
    "save": "<path d='M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z' /> <path d='M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7' /> <path d='M7 3v4a1 1 0 0 0 1 1h7' />",
    "save-all": "<path d='M10 2v3a1 1 0 0 0 1 1h5' /> <path d='M18 18v-6a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6' /> <path d='M18 22H4a2 2 0 0 1-2-2V6' /> <path d='M8 18a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9.172a2 2 0 0 1 1.414.586l2.828 2.828A2 2 0 0 1 22 6.828V16a2 2 0 0 1-2.01 2z' />",
    "scaling": "<path d='M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7' /> <path d='M16 3h5v5' /> <path d='m21 3-6.5 6.5' /> <path d='M7 17h.01' /> <path d='M11 17h.01' /> <path d='M7 13h.01' />",
    "settings": "<path d='M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915' /> <circle cx='12' cy='12' r='3' />",
    "square-dashed": "<path d='M5 3a2 2 0 0 0-2 2' /> <path d='M19 3a2 2 0 0 1 2 2' /> <path d='M21 19a2 2 0 0 1-2 2' /> <path d='M5 21a2 2 0 0 1-2-2' /> <path d='M9 3h1' /> <path d='M9 21h1' /> <path d='M14 3h1' /> <path d='M14 21h1' /> <path d='M3 9v1' /> <path d='M21 9v1' /> <path d='M3 14v1' /> <path d='M21 14v1' />",
    "square-plus": "<rect width='18' height='18' x='3' y='3' rx='2' /> <path d='M8 12h8' /> <path d='M12 8v8' />",
    "trash-2": "<path d='M10 11v6' /> <path d='M14 11v6' /> <path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' /> <path d='M3 6h18' /> <path d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' />",
    "x": "<path d='M18 6 6 18' /> <path d='m6 6 12 12' />",
}

_LUCIDE_TPL = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
)

_LUCIDE_TPL = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
)
_LUCIDE_PIXMAP_CACHE: dict = {}


def lucide_pixmap(name: str, color: str = "#A6ADB6", size: int = 18, stroke: float = 1.8) -> QPixmap:
    """Render a Lucide glyph to a crisp (2x) recolored pixmap. Cached by params."""
    key = (name, color, size, stroke)
    cached = _LUCIDE_PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    inner = _LUCIDE_ICONS.get(name, "")
    if not inner:
        # A missing glyph silently renders an empty button, which is very easy to
        # ship by accident — make it obvious in dev instead.
        pass  # unknown glyph renders empty
    # Glyph bodies may carry their own {color} (e.g. filled shapes), so expand the
    # body first — placeholders inside `inner` aren't seen by the outer format().
    inner = inner.replace("{color}", color)
    svg = _LUCIDE_TPL.format(color=color, sw=stroke, inner=inner)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    _LUCIDE_PIXMAP_CACHE[key] = pm
    return pm


_ARROW_FILE_CACHE: dict = {}


def lucide_arrow_url(name: str, color: str, size: int = 16,
                     stroke: float = 2.6) -> str:
    """Render an icon to a PNG on disk and return a stylesheet-ready URL.

    Qt stylesheets can only point sub-control arrows at an image, and the CSS
    border-triangle trick renders as small blocks rather than arrows in this
    theme — so the spin buttons get the same chevrons the rest of the app uses.
    Cached per (name, colour, size) because the sheet is rebuilt on theme change.
    """
    key = (name, color, size, stroke)
    hit = _ARROW_FILE_CACHE.get(key)
    if hit is not None and Path(hit).exists():
        return hit
    folder = Path(tempfile.gettempdir()) / "captioning_kit_icons"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "_", f"{name}_{color}_{size}_{stroke}".lower())
    path = folder / f"{safe}.png"
    if not path.exists():
        pixmap = lucide_pixmap(name, color, size, stroke)
        if not pixmap.save(str(path), "PNG"):
            return ""
    url = path.as_posix()
    _ARROW_FILE_CACHE[key] = url
    return url


def lucide_icon(name: str, color: str = "#A6ADB6", size: int = 18, stroke: float = 1.8) -> QIcon:
    return QIcon(lucide_pixmap(name, color, size, stroke))


# Motion timings — keep animated widgets feeling consistent across both apps.
MOTION_FAST = 140   # small state flips (toggle knobs)
MOTION_MED = 180    # larger surfaces (slide-overs, panel collapse)

# Distinct per-item colours, cycled by index, for anything that needs several
# individually identifiable marks on one canvas. Deliberately not the accent.
BOX_PALETTE = (
    "#E8A13C", "#2FC6B3", "#E5594B", "#B07CF0",
    "#5BC85B", "#F06FB0", "#E8D44C", "#4FB0E0",
)


def box_color_for(index: int) -> str:
    return BOX_PALETTE[index % len(BOX_PALETTE)]
