"""Instrument configuration tab.

Lets the user add, edit, and remove the instruments used by the Measure tab:
which role they fill (``source`` / ``gate`` / ``meter``), which driver class,
and its key parameters (transport, name, range/gain/etc). Backed by
:class:`InstrumentRegistry`, a small observable container that the Measure tab
reads from and reacts to via the ``changed`` signal -- so editing an
instrument here updates the Measure tab immediately.

v1 only exposes dummy transports wired to a shared simulated DUT (the same
Coulomb-diamond model used everywhere else in the app); real VISA resources
are entered as a resource string and constructed the same way
:func:`emeas.gui.app.build_instruments` already does it, but are not
exercised here without hardware.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emeas import DummyTransport, HP34401A, YokogawaGS200
from emeas.dummy import CoulombDiamondModel, MeasuredDataModel
from emeas.transport import VisaTransport, list_gpib_resources


def default_dut() -> CoulombDiamondModel:
    """The synthetic Coulomb-diamond DUT used when no measured file is loaded.

    Same parameters as :func:`emeas.gui.app.build_instruments` so switching
    back from a measured-data DUT restores the familiar demo physics.
    """
    return CoulombDiamondModel(period=0.4, ec=0.3, gamma=0.03, noise=0.01, seed=0)

_DRIVERS = {
    "YokogawaGS200 (source)": YokogawaGS200,
    "HP34401A (meter)": HP34401A,
}

#: driver guessed from an *IDN? response when auto-adding discovered GPIB
#: instruments; unrecognized instruments default to YokogawaGS200 as a source.
_IDN_DRIVER_HINTS = [
    (("GS200", "YOKOGAWA"), "YokogawaGS200 (source)"),
    (("34401",), "HP34401A (meter)"),
]

#: the dummy rig auto-loaded when a GPIB search finds nothing connected
_DUMMY_RIG = (
    [{"role": f"yoko{i}", "driver_label": "YokogawaGS200 (source)", "name": f"yoko{i}",
      "use_visa": False, "visa_resource": "", "channel": f"yoko{i}",
      "voltage_range": 10.0, "gain": 1.0} for i in range(1, 5)]
    + [{"role": f"meter{i}", "driver_label": "HP34401A (meter)", "name": f"meter{i}",
        "use_visa": False, "visa_resource": "", "channel": f"meter{i}",
        "voltage_range": 10.0, "gain": 1.0} for i in range(1, 3)]
)


class InstrumentRegistry(QObject):
    """Holds the live instrument set + the shared dummy DUT they act on.

    Other windows read :attr:`instruments` and connect to :attr:`changed` to
    react when instruments are added, edited, or removed here.
    """

    changed = pyqtSignal()

    def __init__(self, instruments: dict, dut=None):
        super().__init__()
        self.instruments = dict(instruments)
        self.dut = dut if dut is not None else CoulombDiamondModel(period=0.4, ec=0.3, gamma=0.03, noise=0.01, seed=0)

    def set_instrument(self, role: str, instrument) -> None:
        self.instruments[role] = instrument
        self.changed.emit()

    def remove_instrument(self, role: str) -> None:
        self.instruments.pop(role, None)
        self.changed.emit()

    def build_and_set(self, values: dict):
        """Construct an instrument from an ``_EditDialog.values()``-shaped dict and register it.

        Shared by the Instruments tab's Add/Edit dialogs and by
        :meth:`load_snapshot`, so both go through the same driver-dispatch
        logic. Stores ``values`` on the instrument as ``_config`` so
        :meth:`to_snapshot` can recover exactly what was used to build it.
        Raises on failure (bad VISA resource, etc.) -- callers decide how to
        surface that to the user.
        """
        driver_cls = _DRIVERS[values["driver_label"]]
        if values["use_visa"]:
            transport = VisaTransport(values["visa_resource"])
            address = values["visa_resource"]
        else:
            transport = DummyTransport(self.dut, channel=values["channel"])
            address = None

        kwargs = dict(name=values["name"] or values["role"], address=address,
                      series_resistance=values.get("series_resistance", 0.0))
        if driver_cls is YokogawaGS200:
            kwargs["voltage_range"] = values["voltage_range"]
        elif driver_cls is HP34401A:
            kwargs["gain"] = values["gain"]
            kwargs["voltage_range"] = values["voltage_range"]

        instrument = driver_cls(transport, **kwargs)
        instrument._config = dict(values)
        self.set_instrument(values["role"], instrument)
        return instrument

    def search_gpib(self) -> tuple[list[str], list[str]]:
        """Discover GPIB instruments and load them (or a dummy rig if none found).

        Returns ``(added_roles, errors)``. If real GPIB resources are found,
        each is auto-added with a driver guessed from its ``*IDN?`` response
        (defaulting to a source if unrecognized) and a generic role name
        (``gpibN``); a resource that fails to open/query is skipped and its
        message collected in ``errors`` rather than aborting the whole scan.
        If none are found (no VISA backend, nothing connected, or the scan
        otherwise comes up empty), the current instrument set is replaced with
        a dummy rig of 4 YokogawaGS200 + 2 HP34401A, each on a distinct
        simulated channel.
        """
        resources = list_gpib_resources()
        if not resources:
            self.load_snapshot(_DUMMY_RIG)
            return [cfg["role"] for cfg in _DUMMY_RIG], []

        added: list[str] = []
        errors: list[str] = []
        for i, resource in enumerate(resources):
            driver_label = self._guess_driver(resource)
            role = f"gpib{i}"
            values = {
                "role": role, "driver_label": driver_label, "name": resource,
                "use_visa": True, "visa_resource": resource, "channel": "",
                "voltage_range": 10.0, "gain": 1.0,
            }
            try:
                self.build_and_set(values)
                added.append(role)
            except Exception as exc:
                errors.append(f"{resource}: {exc}")
        return added, errors

    @staticmethod
    def _guess_driver(resource: str) -> str:
        """Best-effort driver guess from a resource's *IDN? response.

        Falls back to a source driver if the instrument can't be queried or
        its identification string isn't recognized -- the user can always fix
        the driver assignment afterward in the Instruments tab.
        """
        try:
            probe = VisaTransport(resource)
            try:
                idn = probe.query("*IDN?").upper()
            finally:
                probe.close()
        except Exception:
            return _IDN_DRIVER_HINTS[0][1]

        for keywords, driver_label in _IDN_DRIVER_HINTS:
            if any(kw in idn for kw in keywords):
                return driver_label
        return _IDN_DRIVER_HINTS[0][1]

    def set_dut(self, model) -> None:
        """Swap the shared dummy DUT and re-wire every dummy instrument onto it.

        Instruments on a :class:`~emeas.transport.DummyTransport` are rebuilt
        from their stored ``_config`` (so they get a fresh transport bound to
        the new model, on the same channel); VISA instruments are untouched.
        Emits :attr:`changed` once at the end.
        """
        self.dut = model
        rebuilt = []
        for role, inst in self.instruments.items():
            if isinstance(inst.transport, DummyTransport) and hasattr(inst, "_config"):
                rebuilt.append(inst._config)
        self.blockSignals(True)
        try:
            for config in rebuilt:
                self.build_and_set(config)
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def dut_snapshot(self) -> dict:
        """Serializable form of the current DUT model choice."""
        if isinstance(self.dut, MeasuredDataModel):
            return {"kind": "measured", "path": self.dut.path or ""}
        return {"kind": "diamonds"}

    def load_dut_snapshot(self, snapshot: dict) -> None:
        """Restore the DUT from :meth:`dut_snapshot`'s output.

        Falls back to the synthetic diamonds model if the measured file is
        missing or no longer parses -- the autosave should never block launch.
        """
        if snapshot.get("kind") == "measured":
            try:
                self.set_dut(MeasuredDataModel.from_file(snapshot.get("path", "")))
                return
            except (OSError, ValueError):
                pass
        self.set_dut(default_dut())

    def to_snapshot(self) -> list[dict]:
        """Serializable form of every instrument, for autosave/history."""
        return [inst._config for inst in self.instruments.values() if hasattr(inst, "_config")]

    def load_snapshot(self, instruments: list[dict]) -> None:
        """Replace the current instrument set with ``instruments`` (from :meth:`to_snapshot`)."""
        self.instruments.clear()
        for values in instruments:
            self.build_and_set(values)
        self.changed.emit()


class _EditDialog(QDialog):
    """Add/edit form for a single instrument entry."""

    def __init__(self, parent=None, *, role: str = "source", driver_label: str | None = None,
                 name: str = "", channel: str = "", use_visa: bool = False,
                 visa_resource: str = "", numeric: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add instrument" if driver_label is None else "Edit instrument")
        numeric = numeric or {}

        form = QFormLayout(self)

        self.role = QLineEdit(role)
        self.role.setPlaceholderText("unique name, e.g. yoko1 / yoko2 / meter1")
        driver_labels = list(_DRIVERS)
        self.driver = QComboBox(); self.driver.addItems(driver_labels)
        if driver_label in driver_labels:
            self.driver.setCurrentText(driver_label)

        self.name = QLineEdit(name)
        self.transport_kind = QComboBox(); self.transport_kind.addItems(["Dummy", "VISA"])
        self.transport_kind.setCurrentText("VISA" if use_visa else "Dummy")

        self.channel = QLineEdit(channel or role)
        self.channel.setPlaceholderText("dummy DUT channel, e.g. bias / gate / meter")

        self.visa_resource = QLineEdit(visa_resource)
        self.visa_resource.setPlaceholderText("GPIB0::N::INSTR")

        # A handful of shared numeric knobs; not every driver uses every one.
        self.voltage_range = QDoubleSpinBox(); self.voltage_range.setRange(0.001, 1000); self.voltage_range.setDecimals(3)
        self.voltage_range.setValue(numeric.get("voltage_range", 10.0))
        self.gain = QDoubleSpinBox(); self.gain.setRange(0.001, 1e6); self.gain.setDecimals(3)
        self.gain.setValue(numeric.get("gain", 1.0))
        self.series_resistance = QDoubleSpinBox(); self.series_resistance.setRange(0.0, 1e12)
        self.series_resistance.setDecimals(1); self.series_resistance.setSuffix(" Ω")
        self.series_resistance.setValue(numeric.get("series_resistance", 0.0))
        self.series_resistance.setToolTip("Known line/output resistance in series with the DUT")

        form.addRow("Role", self.role)
        form.addRow("Driver", self.driver)
        form.addRow("Display name", self.name)
        form.addRow("Transport", self.transport_kind)
        form.addRow("Dummy channel", self.channel)
        form.addRow("VISA resource", self.visa_resource)
        form.addRow("Voltage range (V)", self.voltage_range)
        form.addRow("Gain", self.gain)
        form.addRow("Series resistance", self.series_resistance)

        self.transport_kind.currentTextChanged.connect(self._on_transport_changed)
        self.driver.currentTextChanged.connect(self._on_driver_changed)
        self._on_transport_changed(self.transport_kind.currentText())
        self._on_driver_changed(self.driver.currentText())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_transport_changed(self, kind: str) -> None:
        is_visa = kind == "VISA"
        self.visa_resource.setEnabled(is_visa)
        self.channel.setEnabled(not is_visa)

    def _on_driver_changed(self, label: str) -> None:
        is_meter = _DRIVERS[label] is HP34401A
        self.gain.setEnabled(is_meter)
        self.voltage_range.setEnabled(True)

    def values(self) -> dict:
        return {
            "role": self.role.text().strip(),
            "driver_label": self.driver.currentText(),
            "name": self.name.text().strip(),
            "use_visa": self.transport_kind.currentText() == "VISA",
            "visa_resource": self.visa_resource.text().strip(),
            "channel": self.channel.text().strip() or self.role.text().strip(),
            "voltage_range": self.voltage_range.value(),
            "gain": self.gain.value(),
            "series_resistance": self.series_resistance.value(),
        }


class InstrumentsTab(QWidget):
    """Tab for managing the instrument set used by Measure."""

    def __init__(self, registry: InstrumentRegistry):
        super().__init__()
        self._registry = registry
        self._build_ui()
        self._refresh_table()
        # the registry can change from outside this tab too (autosave restore
        # on launch, File > Load configuration...), so stay in sync with it
        registry.changed.connect(self._refresh_table)

    _DUT_SYNTHETIC = "Coulomb diamonds (synthetic)"
    _DUT_MEASURED = "Measured data file…"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("Instruments used by the Measure tab. Changes apply immediately."))

        # DUT model picker: what the *dummy* instruments are wired to. Real
        # (VISA) instruments talk to hardware and ignore this entirely.
        dut_row = QHBoxLayout()
        dut_row.addWidget(QLabel("DUT model (dummy mode):"))
        self.dut_combo = QComboBox()
        self.dut_combo.addItems([self._DUT_SYNTHETIC, self._DUT_MEASURED])
        self.dut_combo.activated.connect(self._on_dut_choice)
        dut_row.addWidget(self.dut_combo)
        self.dut_path_label = QLabel("")
        dut_row.addWidget(self.dut_path_label, stretch=1)
        root.addLayout(dut_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["role", "driver", "name", "transport"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add…"); add_btn.clicked.connect(self._add)
        edit_btn = QPushButton("Edit…"); edit_btn.clicked.connect(self._edit)
        remove_btn = QPushButton("Remove"); remove_btn.clicked.connect(self._remove)
        search_btn = QPushButton("Search for GPIB instruments")
        search_btn.clicked.connect(self._search_gpib)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(search_btn)
        root.addLayout(btn_row)

    def _on_dut_choice(self, index: int) -> None:
        choice = self.dut_combo.itemText(index)
        if choice == self._DUT_MEASURED:
            import os

            from PyQt6.QtWidgets import QFileDialog

            start_dir = "experimental_data_examples" if os.path.isdir("experimental_data_examples") else ""
            path, _ = QFileDialog.getOpenFileName(
                self, "Open measured 2D map", start_dir, "Sweep data (*.txt *.dat *.tsv);;All files (*)")
            if not path:
                self._sync_dut_row()  # user cancelled -- revert to actual state
                return
            try:
                model = MeasuredDataModel.from_file(path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Measured data file", f"Could not load {path}:\n{exc}")
                self._sync_dut_row()
                return
            self._registry.set_dut(model)
        else:
            if not isinstance(self._registry.dut, CoulombDiamondModel):
                self._registry.set_dut(default_dut())
        self._sync_dut_row()

    def _sync_dut_row(self) -> None:
        """Make the DUT combo + path label reflect the registry's actual DUT."""
        measured = isinstance(self._registry.dut, MeasuredDataModel)
        self.dut_combo.setCurrentText(self._DUT_MEASURED if measured else self._DUT_SYNTHETIC)
        self.dut_path_label.setText(self._registry.dut.path or "" if measured else "")

    def _refresh_table(self) -> None:
        self._sync_dut_row()
        insts = self._registry.instruments
        self.table.setRowCount(len(insts))
        for r, (role, inst) in enumerate(insts.items()):
            transport = "VISA" if isinstance(inst.transport, VisaTransport) else "Dummy"
            values = [role, type(inst).__name__, inst.get_name(), transport]
            for c, val in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def _selected_role(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).text()

    def _add(self) -> None:
        dlg = _EditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply(dlg.values())

    def _edit(self) -> None:
        role = self._selected_role()
        if role is None:
            return
        inst = self._registry.instruments[role]
        is_visa = isinstance(inst.transport, VisaTransport)
        driver_label = next((lbl for lbl, cls in _DRIVERS.items() if isinstance(inst, cls)), list(_DRIVERS)[0])
        numeric = {"voltage_range": getattr(inst, "voltage_range", 10.0), "gain": getattr(inst, "gain", 1.0),
                   "series_resistance": getattr(inst, "series_resistance", 0.0)}
        dlg = _EditDialog(
            self, role=role, driver_label=driver_label, name=inst.get_name(),
            use_visa=is_visa, visa_resource=inst.address or "", numeric=numeric,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply(dlg.values())

    def _remove(self) -> None:
        role = self._selected_role()
        if role is None:
            return
        if QMessageBox.question(self, "Remove instrument", f"Remove the '{role}' instrument?") == QMessageBox.StandardButton.Yes:
            self._registry.remove_instrument(role)
            self._refresh_table()

    def _search_gpib(self) -> None:
        found = list_gpib_resources()
        if not found and self._registry.instruments:
            if QMessageBox.question(
                self, "No GPIB instruments found",
                "No GPIB instruments were found. Replace the current instrument set with "
                "a dummy rig (4x YokogawaGS200 + 2x HP34401A) instead?",
            ) != QMessageBox.StandardButton.Yes:
                return

        added, errors = self._registry.search_gpib()
        self._refresh_table()

        if errors:
            QMessageBox.warning(self, "Some instruments failed to load", "\n".join(errors))
        if found:
            QMessageBox.information(self, "GPIB search complete", f"Added: {', '.join(added)}")
        else:
            QMessageBox.information(self, "GPIB search complete",
                                     "No GPIB instruments found -- loaded a dummy rig instead.")

    def _apply(self, values: dict) -> None:
        if not values["role"]:
            QMessageBox.warning(self, "Missing name", "Enter a unique instrument name.")
            return
        try:
            self._registry.build_and_set(values)
        except Exception as exc:
            QMessageBox.critical(self, "Failed to create instrument", str(exc))
            return

        self._refresh_table()
