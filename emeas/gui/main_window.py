"""Application shell: a tabbed window with **Instruments**, **Measure**, and
**Browse** tabs.

``InstrumentsTab`` (in :mod:`emeas.gui.instruments`) lets the user add/edit/
remove instruments in an :class:`~emeas.gui.instruments.InstrumentRegistry`.
``MeasureTab`` (in :mod:`emeas.gui.measure`) runs a measurement against the
registry's current instruments and streams it into a plot + the HDF5 store.
``BrowserTab`` (in :mod:`emeas.gui.browser`) reopens and replots saved runs
from the same store. When a run finishes, the window refreshes the browser so
new data shows up immediately.

The whole instrument + sweep setup is autosaved (see :mod:`emeas.gui.config_store`)
on close and shortly after any change, and reloaded automatically next launch;
"Save configuration as..." / "Load configuration..." in the File menu let the
user name and revisit past setups.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
)

from emeas.gui import config_store
from emeas.gui.browser import BrowserTab
from emeas.gui.instruments import InstrumentsTab
from emeas.gui.measure import MeasureTab
from emeas.gui.theme import ThemeWatcher

#: how long to wait after the last change before autosaving (ms)
_AUTOSAVE_DEBOUNCE_MS = 1000


class MainWindow(QMainWindow):
    def __init__(self, registry, store, db_path: str = "emeas_data.h5"):
        super().__init__()
        self.setWindowTitle("emeas — instruments, measurement & browser")
        self._store = store
        self._registry = registry
        self._db_path = db_path
        self._theme_watcher = ThemeWatcher(self)

        self.instruments_tab = InstrumentsTab(registry)
        self.measure_tab = MeasureTab(registry, store, theme_watcher=self._theme_watcher)
        self.browser_tab = BrowserTab(store, theme_watcher=self._theme_watcher)
        self.measure_tab.runFinished.connect(lambda _n: self.browser_tab.refresh())

        tabs = QTabWidget()
        tabs.addTab(self.instruments_tab, "Instruments")
        tabs.addTab(self.measure_tab, "Measure")
        tabs.addTab(self.browser_tab, "Browse")
        self.setCentralWidget(tabs)
        self._tabs = tabs

        self._build_menu()
        self._build_autosave_timer()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_act = file_menu.addAction("Open database…")
        open_act.triggered.connect(self._open_database)
        file_menu.addSeparator()
        save_as_act = file_menu.addAction("Save configuration as…")
        save_as_act.triggered.connect(self._save_configuration_as)
        load_act = file_menu.addAction("Load configuration…")
        load_act.triggered.connect(self._load_configuration_dialog)

    def _open_database(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open HDF5 database", "", "HDF5 (*.h5 *.hdf5);;All files (*)")
        if not path:
            return
        from emeas.storage import H5Store

        new_store = H5Store(path)
        old = self._store
        self._store = new_store
        self._db_path = path
        self.measure_tab.set_store(new_store)
        self.browser_tab.set_store(new_store)
        self.browser_tab.refresh()
        try:
            old.close()
        except Exception:
            pass

    # -- config snapshot -----------------------------------------------------
    def to_snapshot(self) -> dict:
        """Serializable form of the full instrument + sweep setup."""
        return {
            "instruments": self._registry.to_snapshot(),
            "dut": self._registry.dut_snapshot(),
            "measure": self.measure_tab.to_snapshot(),
        }

    def load_snapshot(self, snapshot: dict) -> None:
        """Restore DUT, then instruments, then sweep setup from :meth:`to_snapshot`'s output."""
        if "dut" in snapshot:  # restore before instruments so they bind to the right model
            self._registry.load_dut_snapshot(snapshot["dut"])
        self._registry.load_snapshot(snapshot.get("instruments", []))
        self.measure_tab.load_snapshot(snapshot.get("measure", {}))

    # -- autosave -------------------------------------------------------------
    def _build_autosave_timer(self) -> None:
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_now)
        self._registry.changed.connect(self._schedule_autosave)
        for w in (self.measure_tab.axis_a, self.measure_tab.axis_b):
            w.changed.connect(self._schedule_autosave)
        self.measure_tab.enable_b.stateChanged.connect(self._schedule_autosave)
        self.measure_tab.meter_combo.currentTextChanged.connect(self._schedule_autosave)
        self.measure_tab.settle_ms.valueChanged.connect(self._schedule_autosave)
        self.measure_tab.label.textChanged.connect(self._schedule_autosave)
        self.measure_tab.tags.textChanged.connect(self._schedule_autosave)

    def _schedule_autosave(self, *_args) -> None:
        self._autosave_timer.start(_AUTOSAVE_DEBOUNCE_MS)

    def _autosave_now(self) -> None:
        try:
            config_store.save_autosave(self.to_snapshot(), config_store.autosave_path(self._db_path))
        except OSError:
            pass  # best-effort; autosave failing shouldn't interrupt the user

    def closeEvent(self, event) -> None:
        self._autosave_now()
        super().closeEvent(event)

    # -- named history log -----------------------------------------------------
    def _save_configuration_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save configuration", "Name:")
        if not ok or not name.strip():
            return
        config_store.append_history(self.to_snapshot(), config_store.history_path(self._db_path), name=name.strip())

    def _load_configuration_dialog(self) -> None:
        entries = config_store.load_history(config_store.history_path(self._db_path))
        if not entries:
            QMessageBox.information(self, "Load configuration", "No saved configurations yet.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Load configuration")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Pick a saved configuration to load:"))
        listw = QListWidget()
        for entry in reversed(entries):  # newest first
            item = QListWidgetItem(f"{entry['name']}  ({entry['saved_at']})")
            item.setData(1000, entry["config"])
            listw.addItem(item)
        layout.addWidget(listw)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted and listw.currentItem() is not None:
            self.load_snapshot(listw.currentItem().data(1000))
