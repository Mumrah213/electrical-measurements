"""Match pyqtgraph plot chrome to the running Qt application's palette.

pyqtgraph widgets default to a white background / black foreground regardless
of the Qt application's style, so a plot looks visually disconnected from an
otherwise dark- (or light-) themed window. :func:`apply_plot_theme` recolors a
widget's background, axis lines, tick labels, and grid from
``QApplication.palette()`` instead of hardcoding a light/dark choice -- so it
matches Fusion, a native style, or any stylesheet automatically. Only chrome
changes; trace colors and colormaps (:mod:`emeas.gui.plotting`) are deliberately
chosen for contrast/colorblind-safety and are untouched here.

:class:`ThemeWatcher` re-applies the theme automatically when the OS/app color
scheme changes at runtime (Qt 6.5+), so no restart is needed.
"""

from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication


def plot_colors_from_app() -> dict:
    """Return the ``{"background", "foreground"}`` colors for the active palette."""
    app = QApplication.instance()
    palette = app.palette() if app is not None else QPalette()
    return {
        "background": palette.color(QPalette.ColorRole.Base),
        "foreground": palette.color(QPalette.ColorRole.Text),
    }


def _style_plot_item(plot_item, foreground) -> None:
    pen = pg.mkPen(foreground)
    for axis_name in ("left", "bottom", "right", "top"):
        axis = plot_item.getAxis(axis_name)
        axis.setPen(pen)
        axis.setTextPen(pen)
    plot_item.getViewBox().setBackgroundColor(None)


def apply_plot_theme(*widgets) -> None:
    """Recolor each ``pg.PlotWidget`` / ``pg.ImageView`` to the app's current palette."""
    colors = plot_colors_from_app()
    for widget in widgets:
        if widget is None:
            continue
        if isinstance(widget, pg.PlotWidget):
            widget.setBackground(colors["background"])
            _style_plot_item(widget.getPlotItem(), colors["foreground"])
        elif isinstance(widget, pg.ImageView):
            widget.ui.graphicsView.setBackground(colors["background"])
            _style_plot_item(widget.view, colors["foreground"])
            histogram = widget.ui.histogram
            histogram.setBackground(colors["background"])
            axis = histogram.item.axis
            pen = pg.mkPen(colors["foreground"])
            axis.setPen(pen)
            axis.setTextPen(pen)


class ThemeWatcher(QObject):
    """Emits :attr:`changed` whenever the OS/app color scheme changes (Qt 6.5+)."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QApplication.instance()
        if app is not None:
            app.styleHints().colorSchemeChanged.connect(self.changed.emit)
