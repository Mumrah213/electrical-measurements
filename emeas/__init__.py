"""emeas -- self-standing electrical measurement setup over GPIB.

Each instrument is its own named object; the same classes run against a dummy
backend (no hardware) or real GPIB by swapping only the transport.
"""

from emeas.analysis import butter_filter, diff, remove_noise
from emeas.instrument import Instrument
from emeas.measure import (
    iter_linear_sweep,
    iter_map_2d,
    linear_sweep,
    map_2d,
)
from emeas.meters import HP34401A, Multimeter
from emeas.sources import VoltageSource, YokogawaGS200
from emeas.transport import DummyTransport, Transport, VisaTransport

__all__ = [
    "Instrument",
    "Transport",
    "VisaTransport",
    "DummyTransport",
    "VoltageSource",
    "YokogawaGS200",
    "Multimeter",
    "HP34401A",
    "linear_sweep",
    "map_2d",
    "iter_linear_sweep",
    "iter_map_2d",
    "diff",
    "remove_noise",
    "butter_filter",
]
