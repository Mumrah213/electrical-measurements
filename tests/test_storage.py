import numpy as np
import pytest

from emeas import DummyTransport, HP34401A, YokogawaGS200, iter_linear_sweep, iter_map_2d
from emeas.dummy import ResistorModel
from emeas.storage import H5Store


def _rig():
    dut = ResistorModel(resistance=1e6)
    src = YokogawaGS200(DummyTransport(dut), name="bias", voltage_range=10.0)
    meter = HP34401A(DummyTransport(dut), name="reading", gain=2.0)
    return src, meter


def test_run_numbers_increment_and_persist(tmp_path):
    path = str(tmp_path / "data.h5")
    src, meter = _rig()
    with H5Store(path) as store:
        r1 = store.new_run("1d", instruments={"source": src, "meter": meter})
        r2 = store.new_run("1d", instruments={"source": src, "meter": meter})
        assert r1.run_number == 1
        assert r2.run_number == 2
    # Reopen: counter persisted, next run is 3.
    with H5Store(path) as store:
        r3 = store.new_run("1d", instruments={"source": src})
        assert r3.run_number == 3


def test_append_grows_datasets_and_roundtrips(tmp_path):
    path = str(tmp_path / "data.h5")
    src, meter = _rig()
    with H5Store(path) as store:
        run = store.new_run(
            "1d",
            "sweep A",
            params={"start": -1, "stop": 1, "points": 5},
            instruments={"source": src, "meter": meter},
        )
        for point in iter_linear_sweep(src, meter, -1, 1, 5):
            run.append(point)
        run.close()

        out = store.read_run(1)
        assert out["label"] == "sweep A"
        assert out["params"]["points"] == 5
        assert len(out["data"]["set_voltage"]) == 5
        # gain=2 -> meter.read halves node voltage; check endpoints
        assert out["data"]["reading"][0] == pytest.approx(-0.5)
        assert out["data"]["reading"][-1] == pytest.approx(0.5)


def test_settings_snapshot_recorded(tmp_path):
    path = str(tmp_path / "data.h5")
    src, meter = _rig()
    with H5Store(path) as store:
        store.new_run("1d", instruments={"source": src, "meter": meter})
        out = store.read_run(1)
        assert out["settings"]["source"]["role"] == "source"
        assert out["settings"]["source"]["voltage_range"] == 10.0
        assert out["settings"]["meter"]["gain"] == 2.0
        assert out["settings"]["meter"]["name"] == "reading"


def test_label_rewritable(tmp_path):
    path = str(tmp_path / "data.h5")
    src, _ = _rig()
    with H5Store(path) as store:
        run = store.new_run("1d", instruments={"source": src})
        run.set_label("renamed run")
    with H5Store(path) as store:
        assert store.read_run(1)["label"] == "renamed run"


def test_map_2d_stores_grid_indices(tmp_path):
    path = str(tmp_path / "data.h5")
    src, meter = _rig()
    sy = YokogawaGS200(DummyTransport(), name="gate")
    with H5Store(path) as store:
        run = store.new_run("2d", instruments={"x": src, "y": sy, "meter": meter})
        x = np.linspace(-1, 1, 3)
        y = np.linspace(0, 1, 2)
        for point in iter_map_2d(src, sy, meter, x, y):
            run.append(point)
        run.close()
        out = store.read_run(1)
        assert len(out["data"]["ix"]) == 6
        assert set(out["data"]["ix"].tolist()) == {0, 1, 2}
        assert set(out["data"]["iy"].tolist()) == {0, 1}


def test_list_runs_sorted(tmp_path):
    path = str(tmp_path / "data.h5")
    src, _ = _rig()
    with H5Store(path) as store:
        store.new_run("1d", "a", instruments={"source": src})
        store.new_run("2d", "b", instruments={"source": src})
        runs = store.list_runs()
        assert [r["run_number"] for r in runs] == [1, 2]
        assert runs[1]["kind"] == "2d"


def test_tags_roundtrip_and_points_in_summary(tmp_path):
    path = str(tmp_path / "data.h5")
    src, meter = _rig()
    with H5Store(path) as store:
        run = store.new_run("1d", "tagged", instruments={"source": src, "meter": meter},
                            tags="spin-qubit, cooldown3")
        for p in iter_linear_sweep(src, meter, -1, 1, 4):
            run.append(p)
        run.close()
        summary = store.list_runs()[0]
        assert summary["tags"] == "spin-qubit, cooldown3"
        assert summary["points"] == 4
        assert store.read_run(1)["tags"] == "spin-qubit, cooldown3"


def test_set_label_and_set_tags_persist(tmp_path):
    path = str(tmp_path / "data.h5")
    src, _ = _rig()
    with H5Store(path) as store:
        store.new_run("1d", "orig", instruments={"source": src})
        store.set_label(1, "renamed")
        store.set_tags(1, "projectX")
    with H5Store(path) as store:
        out = store.read_run(1)
        assert out["label"] == "renamed"
        assert out["tags"] == "projectX"


def test_read_run_backcompat_missing_tags(tmp_path):
    """A run group written without the tags attr (older files) still loads."""
    import h5py

    path = str(tmp_path / "old.h5")
    src, _ = _rig()
    with H5Store(path) as store:
        store.new_run("1d", "legacy", instruments={"source": src})
    # simulate an older file: delete the tags attr
    with h5py.File(path, "a") as f:
        del f["runs"]["run_00001"].attrs["tags"]
    with H5Store(path) as store:
        out = store.read_run(1)
        assert out["tags"] == ""
        assert store.list_runs()[0]["tags"] == ""
