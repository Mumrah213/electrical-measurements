"""Sweep-axis and fixed-value widgets: instrument dropdowns with mutual exclusion.

A :class:`SweepAxisWidget` represents one sweep axis, e.g. "Sweep A". It holds
one or more rows, each picking a source instrument (via a dropdown populated
from the current :class:`~emeas.gui.instruments.InstrumentRegistry`) plus a
start/stop for that instrument. All rows in an axis share one point count and
are driven together at each step index -- e.g. yoko1 start/end and yoko2
start/end swept synchronized -- via
:func:`emeas.measure.iter_linear_sweep_group`. "+ instrument" appends another
row to sweep in lockstep with the first; each row has its own "-" button to
remove just that row.

:class:`FixedValueWidget` ("Sweep C" in the Measure tab) is the same
row-of-instrument-dropdowns idea but each row picks just one constant value
(no start/stop/points -- there's nothing to sweep), passed as the ``fixed=``
mapping to :func:`emeas.measure.iter_linear_sweep_group` /
:func:`emeas.measure.iter_map_2d_group` so those instruments are set once at
the start of a run and held there.

A source can only usefully be driven by one row across the *whole*
measurement (Sweep A, Sweep B, *and* Sweep C) -- otherwise it would need two
setpoints at once. Rather than removing already-used instruments from a
dropdown (which would make options vanish confusingly as you configure other
rows), :attr:`_usage_provider` lets a widget see what roles are claimed by
*other* axes; those entries stay visible but greyed out, disabled, and
suffixed with which axis has them (e.g. "yoko2 (B)"). This logic is shared by
both widgets via :class:`_ExclusiveRoleGroupBox`, which also gives each group
a distinct tinted background (:func:`axis_tint_stylesheet`) so Sweep A/B/C are
visually distinct at a glance.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QPalette, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

#: base hue per axis label -- blended with the app's own palette in
#: :func:`axis_tint_stylesheet` so the tint reads correctly in light or dark
#: mode rather than being a fixed hardcoded color.
_AXIS_HUES = {
    "A": QColor("#3b82f6"),  # blue
    "B": QColor("#22c55e"),  # green
    "C": QColor("#f59e0b"),  # amber
}


def axis_tint_stylesheet(axis_label: str) -> str:
    """QGroupBox stylesheet giving ``axis_label`` (A/B/C/...) a subtle tinted
    background blended with the current app palette, so Sweep A/B/C are
    visually distinct at a glance but the tint still adapts to light/dark mode.
    """
    hue = _AXIS_HUES.get(axis_label)
    if hue is None:
        return ""
    app = QApplication.instance()
    base = app.palette().color(QPalette.ColorRole.Base) if app is not None else QColor("white")
    # Blend mostly toward the palette base color so text/contrast stays close
    # to normal, with just enough of the hue to read as "this group's color."
    mix = 0.16
    blended = QColor(
        round(base.red() * (1 - mix) + hue.red() * mix),
        round(base.green() * (1 - mix) + hue.green() * mix),
        round(base.blue() * (1 - mix) + hue.blue() * mix),
    )
    border = hue.name()
    return (
        f"QGroupBox {{ background-color: {blended.name()}; "
        f"border: 1px solid {border}; border-radius: 4px; margin-top: 8px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; "
        f"color: {border}; font-weight: bold; }}"
    )


class _ExclusiveRoleGroupBox(QGroupBox):
    """Shared machinery for a group box of rows, each with an instrument dropdown
    that must not claim the same role as another row here or in a peer group box.

    Subclasses provide ``_rows`` (each with a ``source_combo`` attribute and a
    ``remove_btn``) and call :meth:`refresh_instrument_choices` /
    :meth:`_select_first_available` at the appropriate row-management points;
    this class owns the dropdown-population/conflict-resolution logic plus the
    per-row grid re-layout used when a row is removed from the middle.
    """

    #: emitted whenever the chosen instruments (or anything else row-specific) change
    changed = pyqtSignal()

    def _init_exclusive_role_group(self, registry, *, role_filter=None, axis_label: str | None = None,
                                    usage_provider=None) -> None:
        self._registry = registry
        self._role_filter = role_filter  # optional callable(role, instrument) -> bool
        #: short tag shown on entries this axis itself claims, e.g. "A"
        self._axis_label = axis_label or self.title()
        #: optional callable() -> dict[role, axis_label] for roles claimed by *other* axes
        self._usage_provider = usage_provider
        self._rows: list = []
        self.apply_tint()

    def apply_tint(self) -> None:
        """(Re)apply this group's A/B/C color coding from the current app palette.

        Called once at construction and again on theme changes (the tint is
        blended with the palette's base color, so it needs recomputing when
        that changes -- see MeasureTab wiring this to the shared ThemeWatcher).
        """
        self.setStyleSheet(axis_tint_stylesheet(self._axis_label))

    @staticmethod
    def _select_first_available(combo: QComboBox) -> None:
        """Default a freshly populated combo to its first *enabled* entry.

        Qt defaults a new model's selection to index 0 regardless of whether
        that entry is disabled (already claimed by another row/axis); without
        this, a new row could silently start on a role another axis already
        has, defeating the whole point of flagging conflicts.
        """
        model = combo.model()
        if model is None:
            return
        for i in range(combo.count()):
            item = model.item(i)
            if item is not None and item.isEnabled():
                combo.setCurrentIndex(i)
                return

    def _on_selection_changed(self, _index: int) -> None:
        # The row whose combo just fired this signal is the "winner" of any
        # collision -- relabel it cosmetically only. Every *other* row in
        # this group is reconciled: if one of them was on the role just
        # claimed, it gets bumped off, matching how a peer group's claim
        # displaces this group's rows (see the cross-axis wiring in
        # measure.py). A peer group also needs to hear about this change, via
        # the caller's usage_provider/changed wiring.
        changed_combo = self.sender()
        for row in self._rows:
            if row.source_combo is changed_combo:
                self.refresh_instrument_choices(row.source_combo)
            else:
                self.refresh_instrument_choices(row.source_combo, reconcile=True)
        self.changed.emit()

    # -- instrument choices ----------------------------------------------
    def refresh_instrument_choices(self, combo: QComboBox | None = None, *, reconcile: bool = False) -> None:
        """Repopulate dropdown(s) from the registry's current instruments.

        A role already picked by *another* row (in this group or, via
        :attr:`_usage_provider`, another group) stays in the list but is
        disabled, greyed out, and suffixed with which group has it -- so
        options never disappear, they just show as unavailable elsewhere.
        Combo item text carries the display label; the underlying role is
        stored as item data (:meth:`_selected_role_for`), since the label may
        have a "(A)"/"(B)"/"(C)" suffix that isn't part of the actual role name.

        By default this only relabels -- it never changes what's selected,
        so calling it after *this* group's own combo just changed doesn't
        second-guess that change. Pass ``reconcile=True`` (used when a peer
        group notifies us that *it* just claimed something) to also reassign
        away from a role a peer has just taken, since in that case this
        group's current pick is the stale one.
        """
        roles = [
            role for role, inst in self._registry.instruments.items()
            if self._role_filter is None or self._role_filter(role, inst)
        ]
        others_used = dict(self._usage_provider()) if self._usage_provider else {}

        combos = [combo] if combo is not None else [row.source_combo for row in self._rows]
        for c in combos:
            current_role = self._selected_role_for(c)
            used_here = {
                self._selected_role_for(row.source_combo) for row in self._rows
                if row.source_combo is not c and self._selected_role_for(row.source_combo)
            }
            reassign = reconcile and (current_role in used_here or current_role in others_used)

            c.blockSignals(True)
            model = QStandardItemModel(c)
            for role in roles:
                display = self._registry.instruments[role].get_name() or role
                label = display
                claimed_by = others_used.get(role)
                mine = role == current_role and not reassign
                claimant = None
                if not mine and role in used_here:
                    claimant = self._axis_label
                elif not mine and claimed_by is not None:
                    claimant = claimed_by
                if claimant is not None:
                    label = f"{display} ({claimant})"
                item = QStandardItem(label)
                item.setData(role, Qt.ItemDataRole.UserRole)
                if claimant is not None:
                    item.setEnabled(False)
                    # color-match the claiming axis's hue (Sweep A/B/C group
                    # tint) so it's obvious at a glance who holds this role
                    hue = _AXIS_HUES.get(claimant)
                    item.setForeground(hue if hue is not None else c.palette().mid())
                model.appendRow(item)
            c.setModel(model)

            if current_role in roles and not reassign:
                c.setCurrentIndex(roles.index(current_role))
            c.blockSignals(False)
            if reassign:
                # setModel() left Qt's own index-0 default in place; replace
                # it with the first role this combo can actually claim. Fires
                # currentIndexChanged (not blocked here) so peers hear about it.
                self._select_first_available(c)

    @staticmethod
    def _selected_role_for(combo: QComboBox) -> str:
        idx = combo.currentIndex()
        if idx < 0 or combo.model() is None:
            return ""
        item = combo.model().item(idx)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else combo.currentText()

    def selected_roles(self) -> list[str]:
        return [self._selected_role_for(row.source_combo) for row in self._rows]

    def row_count(self) -> int:
        return len(self._rows)

    def _set_role_on_combo(self, combo: QComboBox, role: str) -> None:
        """Select ``role`` on ``combo`` by underlying role data, not display text."""
        for i in range(combo.count()):
            item = combo.model().item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == role:
                combo.setCurrentIndex(i)
                return

    # -- shared row layout -------------------------------------------------
    def _relayout_rows(self) -> None:
        """Re-place every row's widgets in the grid at its current index.

        Needed because a row can now be removed from the middle (its own "-"
        button, not just "remove the last row"), so surviving rows below it
        must shift up by one grid row.
        """
        for r, row in enumerate(self._rows, start=1):
            for col, widget in enumerate(row.widgets()):
                self._rows_layout.addWidget(widget, r, col)

    def _remove_specific_row(self, row) -> None:
        if row not in self._rows:
            return
        self._rows.remove(row)
        for w in row.widgets():
            self._rows_layout.removeWidget(w)
            w.deleteLater()
        self._relayout_rows()
        self.changed.emit()


class _AxisRow:
    def __init__(self, source_combo: QComboBox, start: QDoubleSpinBox, stop: QDoubleSpinBox, remove_btn: QPushButton):
        self.source_combo = source_combo
        self.start = start
        self.stop = stop
        self.remove_btn = remove_btn

    def widgets(self) -> list[QWidget]:
        return [self.source_combo, self.start, self.stop, self.remove_btn]


class SweepAxisWidget(_ExclusiveRoleGroupBox):
    """One sweep axis: N instrument rows (synced) + a shared point count."""

    def __init__(self, title: str, registry, *, role_filter=None, default_points: int = 61,
                 axis_label: str | None = None, usage_provider=None):
        super().__init__(title)
        self._init_exclusive_role_group(registry, role_filter=role_filter, axis_label=axis_label,
                                         usage_provider=usage_provider)

        outer = QVBoxLayout(self)
        self._rows_layout = QGridLayout()
        outer.addLayout(self._rows_layout)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ instrument")
        self.add_btn.clicked.connect(self._add_row)
        btn_row.addWidget(self.add_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(QLabel("points:"))
        self.points_spin = QSpinBox(); self.points_spin.setRange(2, 100000); self.points_spin.setValue(default_points)
        self.points_spin.valueChanged.connect(self.changed.emit)
        btn_row.addWidget(self.points_spin)
        outer.addLayout(btn_row)

        self._rows_layout.addWidget(QLabel("instrument"), 0, 0)
        self._rows_layout.addWidget(QLabel("start"), 0, 1)
        self._rows_layout.addWidget(QLabel("stop"), 0, 2)

        self._add_row()

    # -- row management ------------------------------------------------
    def _add_row(self) -> None:
        combo = QComboBox()
        self.refresh_instrument_choices(combo)
        self._select_first_available(combo)
        combo.currentIndexChanged.connect(self._on_selection_changed)
        start = QDoubleSpinBox(); start.setRange(-100, 100); start.setSingleStep(0.1)
        stop = QDoubleSpinBox(); stop.setRange(-100, 100); stop.setSingleStep(0.1); stop.setValue(0.5)
        start.valueChanged.connect(self.changed.emit)
        stop.valueChanged.connect(self.changed.emit)
        if len(self._rows) == 0:
            start.setValue(-0.5)
        else:
            start.setValue(-0.5 / len(self._rows))
            stop.setValue(0.5 / len(self._rows))

        remove_btn = QPushButton("−")
        remove_btn.setFixedWidth(24)
        remove_btn.setToolTip("Remove this instrument from Sweep A/B")

        row = _AxisRow(combo, start, stop, remove_btn)
        remove_btn.clicked.connect(lambda: self._remove_specific_row(row))
        self._rows.append(row)
        self._relayout_rows()
        self.changed.emit()

    # -- values ------------------------------------------------------------
    def bounds(self) -> list[tuple[float, float]]:
        return [(row.start.value(), row.stop.value()) for row in self._rows]

    def point_count(self) -> int:
        return self.points_spin.value()

    def load_rows(self, roles: list[str], bounds: list[tuple[float, float]], points: int) -> None:
        """Restore rows from saved ``roles``/``bounds`` plus a shared ``points``.

        Adds/removes rows to match ``len(roles)``, then sets each row's
        instrument choice and start/stop. A role no longer present in the
        registry is left unset on that row (the combo just won't match it)
        rather than raising -- the instrument may have been removed since the
        snapshot was saved.
        """
        while len(self._rows) < len(roles):
            self._add_row()
        while len(self._rows) > max(len(roles), 1):
            self._remove_specific_row(self._rows[-1])

        for row, role, (start, stop) in zip(self._rows, roles, bounds):
            self._set_role_on_combo(row.source_combo, role)
            row.start.setValue(start)
            row.stop.setValue(stop)
        self.points_spin.setValue(points)
        self.refresh_instrument_choices()


class _FixedRow:
    def __init__(self, source_combo: QComboBox, value: QDoubleSpinBox, remove_btn: QPushButton):
        self.source_combo = source_combo
        self.value = value
        self.remove_btn = remove_btn

    def widgets(self) -> list[QWidget]:
        return [self.source_combo, self.value, self.remove_btn]


class FixedValueWidget(_ExclusiveRoleGroupBox):
    """"Sweep C": N instrument rows, each held at one constant value for a run.

    Unlike :class:`SweepAxisWidget` there's no start/stop/points -- just a
    single setpoint per row, applied once at the start of a run via the
    ``fixed=`` mapping already accepted by
    :func:`emeas.measure.iter_linear_sweep_group` /
    :func:`emeas.measure.iter_map_2d_group`.
    """

    def __init__(self, title: str, registry, *, role_filter=None,
                 axis_label: str | None = None, usage_provider=None):
        super().__init__(title)
        self._init_exclusive_role_group(registry, role_filter=role_filter, axis_label=axis_label,
                                         usage_provider=usage_provider)

        outer = QVBoxLayout(self)
        self._rows_layout = QGridLayout()
        outer.addLayout(self._rows_layout)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ instrument")
        self.add_btn.clicked.connect(self._add_row)
        btn_row.addWidget(self.add_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        self._rows_layout.addWidget(QLabel("instrument"), 0, 0)
        self._rows_layout.addWidget(QLabel("value"), 0, 1)

    # -- row management ------------------------------------------------
    def _add_row(self) -> None:
        combo = QComboBox()
        self.refresh_instrument_choices(combo)
        self._select_first_available(combo)
        combo.currentIndexChanged.connect(self._on_selection_changed)
        value = QDoubleSpinBox(); value.setRange(-100, 100); value.setSingleStep(0.1)
        value.valueChanged.connect(self.changed.emit)

        remove_btn = QPushButton("−")
        remove_btn.setFixedWidth(24)
        remove_btn.setToolTip("Remove this instrument from Sweep C")

        row = _FixedRow(combo, value, remove_btn)
        remove_btn.clicked.connect(lambda: self._remove_specific_row(row))
        self._rows.append(row)
        self._relayout_rows()
        self.changed.emit()

    # -- values ------------------------------------------------------------
    def values(self) -> list[float]:
        return [row.value.value() for row in self._rows]

    def load_rows(self, roles: list[str], values: list[float]) -> None:
        """Restore rows from saved ``roles``/``values`` (see :meth:`to_snapshot` callers)."""
        while len(self._rows) < len(roles):
            self._add_row()
        while len(self._rows) > len(roles):
            self._remove_specific_row(self._rows[-1])

        for row, role, value in zip(self._rows, roles, values):
            self._set_role_on_combo(row.source_combo, role)
            row.value.setValue(value)
        self.refresh_instrument_choices()
