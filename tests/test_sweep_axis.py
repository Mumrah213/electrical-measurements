import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from emeas.gui.instruments import InstrumentRegistry  # noqa: E402
from emeas.gui.sweep_axis import FixedValueWidget, SweepAxisWidget, axis_tint_stylesheet  # noqa: E402


#: module-level reference -- without this, nothing keeps the QApplication
#: singleton's Python wrapper alive between calls and PyQt6 garbage-collects
#: the underlying C++ object, crashing the next widget construction.
_qapp = None


def _app():
    global _qapp
    _qapp = QApplication.instance() or QApplication([])
    return _qapp


def _registry():
    from emeas import DummyTransport, HP34401A, YokogawaGS200

    source = YokogawaGS200(DummyTransport(), name="source")
    gate = YokogawaGS200(DummyTransport(), name="gate")
    meter = HP34401A(DummyTransport(), name="meter")
    return InstrumentRegistry({"source": source, "gate": gate, "meter": meter})


def test_load_rows_grows_and_sets_values():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry())
    axis.load_rows(["source", "gate"], [(-1.0, 1.0), (-0.5, 0.5)], 25)
    assert axis.row_count() == 2
    assert axis.selected_roles() == ["source", "gate"]
    assert axis.bounds() == [(-1.0, 1.0), (-0.5, 0.5)]
    assert axis.point_count() == 25


def test_load_rows_shrinks():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry())
    axis.load_rows(["source", "gate"], [(-1.0, 1.0), (-0.5, 0.5)], 25)
    axis.load_rows(["meter"], [(0.0, 1.0)], 10)
    assert axis.row_count() == 1
    assert axis.selected_roles() == ["meter"]
    assert axis.bounds() == [(0.0, 1.0)]


def test_load_rows_empty_keeps_one_row():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry())
    axis.load_rows([], [], 40)
    assert axis.row_count() == 1
    assert axis.point_count() == 40


def _labels(combo):
    return [combo.model().item(i).text() for i in range(combo.count())]


def _enabled(combo):
    return [combo.model().item(i).isEnabled() for i in range(combo.count())]


def test_new_row_in_same_axis_avoids_duplicate_default():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry())
    axis._add_row()
    role1 = axis._selected_role_for(axis._rows[0].source_combo)
    role2 = axis._selected_role_for(axis._rows[1].source_combo)
    assert role1 != role2


def test_same_axis_role_used_elsewhere_shown_disabled_and_tagged():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry(), axis_label="A")
    axis._add_row()
    row0, row1 = axis._rows
    role0 = axis._selected_role_for(row0.source_combo)
    labels1 = _labels(row1.source_combo)
    enabled1 = _enabled(row1.source_combo)
    idx = [i for i, l in enumerate(labels1) if l.startswith(role0)][0]
    assert not enabled1[idx]
    assert labels1[idx] == f"{role0} (A)"


def test_cross_axis_claim_disables_and_tags_in_peer():
    _app()
    registry = _registry()
    axis_b_ref = {}

    axis_a = SweepAxisWidget(
        "Sweep A", registry, axis_label="A",
        usage_provider=lambda: {r: "B" for r in axis_b_ref["b"].selected_roles() if r} if "b" in axis_b_ref else {},
    )
    axis_b = SweepAxisWidget(
        "Sweep B", registry, axis_label="B",
        usage_provider=lambda: {r: "A" for r in axis_a.selected_roles() if r},
    )
    axis_b_ref["b"] = axis_b
    axis_a.changed.connect(lambda: axis_b.refresh_instrument_choices(reconcile=True))
    axis_b.changed.connect(lambda: axis_a.refresh_instrument_choices(reconcile=True))
    axis_a.refresh_instrument_choices(reconcile=True)

    role_a = axis_a._selected_role_for(axis_a._rows[0].source_combo)
    role_b = axis_b._selected_role_for(axis_b._rows[0].source_combo)
    assert role_a != role_b  # defaults never collide

    axis_a._set_role_on_combo(axis_a._rows[0].source_combo, role_b)
    # A explicitly took B's role -> A keeps it, B gets bumped off it
    assert axis_a._selected_role_for(axis_a._rows[0].source_combo) == role_b
    assert axis_b._selected_role_for(axis_b._rows[0].source_combo) != role_b

    labels_b = _labels(axis_b._rows[0].source_combo)
    enabled_b = _enabled(axis_b._rows[0].source_combo)
    idx = [i for i, l in enumerate(labels_b) if l.startswith(role_b)][0]
    assert not enabled_b[idx]
    assert labels_b[idx] == f"{role_b} (A)"

    assert set(axis_a.selected_roles()) & set(axis_b.selected_roles()) == set()


def test_within_axis_claim_bumps_the_other_row():
    _app()
    registry = _registry()
    axis_a = SweepAxisWidget("Sweep A", registry, axis_label="A")
    axis_a._add_row()
    row0, row1 = axis_a._rows
    role0 = axis_a._selected_role_for(row0.source_combo)

    axis_a._set_role_on_combo(row1.source_combo, role0)

    # row1 explicitly took row0's role -> row1 keeps it, row0 gets bumped off
    assert axis_a._selected_role_for(row1.source_combo) == role0
    assert axis_a._selected_role_for(row0.source_combo) != role0


# -- FixedValueWidget ("Sweep C") ---------------------------------------------

def test_fixed_value_widget_starts_with_no_rows():
    _app()
    axis_c = FixedValueWidget("Sweep C", _registry())
    assert axis_c.row_count() == 0
    assert axis_c.selected_roles() == []
    assert axis_c.values() == []


def test_fixed_value_widget_add_row_sets_value():
    _app()
    axis_c = FixedValueWidget("Sweep C", _registry())
    axis_c._add_row()
    axis_c._rows[0].value.setValue(1.23)
    assert axis_c.values() == pytest.approx([1.23])


def test_fixed_value_widget_load_rows_round_trip():
    _app()
    axis_c = FixedValueWidget("Sweep C", _registry())
    axis_c.load_rows(["source", "gate"], [0.5, -0.25])
    assert axis_c.selected_roles() == ["source", "gate"]
    assert axis_c.values() == pytest.approx([0.5, -0.25])

    axis_c.load_rows(["meter"], [1.0])
    assert axis_c.row_count() == 1
    assert axis_c.selected_roles() == ["meter"]


def test_sweep_axis_and_fixed_value_widget_are_mutually_exclusive():
    """Sweep A and Sweep C (different widget classes) must not double-claim
    the same instrument -- exercises the shared _ExclusiveRoleGroupBox logic
    across widget types, not just between two SweepAxisWidgets."""
    _app()
    registry = _registry()
    refs = {}

    axis_a = SweepAxisWidget(
        "Sweep A", registry, axis_label="A",
        usage_provider=lambda: {r: "C" for r in refs["c"].selected_roles() if r} if "c" in refs else {},
    )
    axis_c = FixedValueWidget(
        "Sweep C", registry, axis_label="C",
        usage_provider=lambda: {r: "A" for r in axis_a.selected_roles() if r},
    )
    refs["c"] = axis_c
    axis_a.changed.connect(lambda: axis_c.refresh_instrument_choices(reconcile=True))
    axis_c.changed.connect(lambda: axis_a.refresh_instrument_choices(reconcile=True))

    axis_c._add_row()
    role_a = axis_a._selected_role_for(axis_a._rows[0].source_combo)
    role_c = axis_c._selected_role_for(axis_c._rows[0].source_combo)
    assert role_a != role_c  # default placement avoided the collision

    axis_c._set_role_on_combo(axis_c._rows[0].source_combo, role_a)
    # C explicitly claimed A's role -> C keeps it, A gets bumped off
    assert axis_c._selected_role_for(axis_c._rows[0].source_combo) == role_a
    assert axis_a._selected_role_for(axis_a._rows[0].source_combo) != role_a


# -- per-row remove ------------------------------------------------------

def test_remove_middle_row_shifts_others_up_and_keeps_their_values():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry())
    axis._add_row()
    axis._add_row()
    roles_before = axis.selected_roles()
    bounds_before = axis.bounds()

    axis._rows[1].remove_btn.click()

    assert axis.row_count() == 2
    assert axis.selected_roles() == [roles_before[0], roles_before[2]]
    assert axis.bounds() == [bounds_before[0], bounds_before[2]]
    # grid positions are contiguous (1, 2), not (1, 3) with a gap
    for r, row in enumerate(axis._rows, start=1):
        idx = axis._rows_layout.indexOf(row.source_combo)
        assert axis._rows_layout.getItemPosition(idx)[0] == r


def test_fixed_value_widget_remove_specific_row():
    _app()
    axis_c = FixedValueWidget("Sweep C", _registry())
    axis_c._add_row()
    axis_c._add_row()
    axis_c._rows[1].value.setValue(9.0)
    role1 = axis_c.selected_roles()[1]

    axis_c._rows[0].remove_btn.click()

    assert axis_c.row_count() == 1
    assert axis_c.selected_roles() == [role1]
    assert axis_c.values() == pytest.approx([9.0])


# -- color coding ---------------------------------------------------------

def test_axis_tint_stylesheet_distinct_per_label():
    _app()
    a = axis_tint_stylesheet("A")
    b = axis_tint_stylesheet("B")
    c = axis_tint_stylesheet("C")
    assert a and b and c
    assert len({a, b, c}) == 3


def test_unknown_axis_label_gets_no_tint():
    _app()
    assert axis_tint_stylesheet("Z") == ""


def test_group_box_applies_tint_on_construction():
    _app()
    axis = SweepAxisWidget("Sweep A", _registry(), axis_label="A")
    assert axis.styleSheet() == axis_tint_stylesheet("A")
