"""Entry point for the emeas GUI.

Builds a set of (dummy, for now) instruments wired to one shared simulated DUT,
opens an HDF5 database, and launches the main window.

    emeas-gui                  # writes ./emeas_data.h5
    emeas-gui my_fridge.h5     # custom database path
"""

from __future__ import annotations

import sys

from emeas import DummyTransport, HP34401A, YokogawaGS200
from emeas.dummy import CoulombDiamondModel
from emeas.storage import H5Store


def build_instruments() -> dict:
    """Preconfigured dummy rig wired to a Coulomb-diamond quantum-dot DUT.

    The source (source-drain bias) and gate write to the *same* shared model on
    distinct channels, so a 2D map of bias vs gate streams the iconic
    Coulomb-blockade diamond pattern. A 1D bias sweep streams a conductance
    turn-on (blockade -> conducting) at the fixed gate.

    To go to the lab, swap ``DummyTransport(dut, channel=...)`` for
    ``VisaTransport("GPIB0::N::INSTR")`` here -- nothing else changes.
    """
    dut = CoulombDiamondModel(period=0.4, ec=0.3, gamma=0.03, noise=0.01, seed=0)
    source = YokogawaGS200(DummyTransport(dut, channel="bias"), name="source-drain bias", voltage_range=10.0)
    gate = YokogawaGS200(DummyTransport(dut, channel="gate"), name="gate", voltage_range=10.0)
    meter = HP34401A(DummyTransport(dut, channel="meter"), name="conductance", gain=1.0)
    return {"source": source, "gate": gate, "meter": meter}


def main(argv: list[str] | None = None) -> int:
    from PyQt6.QtWidgets import QApplication

    from emeas.gui.main_window import MainWindow

    argv = list(sys.argv if argv is None else argv)
    db_path = argv[1] if len(argv) > 1 else "emeas_data.h5"

    app = QApplication(argv)
    store = H5Store(db_path)
    window = MainWindow(build_instruments(), store)
    window.resize(1000, 600)
    window.show()
    try:
        return app.exec()
    finally:
        store.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
