from emeas.gui import config_store


def test_autosave_round_trip(tmp_path):
    path = config_store.autosave_path(tmp_path / "data.h5")
    snapshot = {"instruments": [{"role": "source"}], "measure": {"label": "x"}}
    config_store.save_autosave(snapshot, path)
    assert config_store.load_autosave(path) == snapshot


def test_autosave_missing_file_returns_none(tmp_path):
    path = config_store.autosave_path(tmp_path / "data.h5")
    assert config_store.load_autosave(path) is None


def test_autosave_corrupt_file_returns_none(tmp_path):
    path = config_store.autosave_path(tmp_path / "data.h5")
    path.write_text("{not valid json")
    assert config_store.load_autosave(path) is None


def test_history_append_and_load(tmp_path):
    path = config_store.history_path(tmp_path / "data.h5")
    config_store.append_history({"a": 1}, path, name="first")
    config_store.append_history({"a": 2}, path, name="second")
    entries = config_store.load_history(path)
    assert [e["name"] for e in entries] == ["first", "second"]
    assert entries[0]["config"] == {"a": 1}
    assert "saved_at" in entries[0]


def test_history_default_name(tmp_path):
    path = config_store.history_path(tmp_path / "data.h5")
    config_store.append_history({"a": 1}, path)
    entries = config_store.load_history(path)
    assert entries[0]["name"] == "config 1"


def test_history_caps_length(tmp_path):
    path = config_store.history_path(tmp_path / "data.h5")
    for i in range(config_store.MAX_HISTORY + 10):
        config_store.append_history({"i": i}, path, name=str(i))
    entries = config_store.load_history(path)
    assert len(entries) == config_store.MAX_HISTORY
    assert entries[-1]["config"] == {"i": config_store.MAX_HISTORY + 9}


def test_history_missing_file_returns_empty_list(tmp_path):
    path = config_store.history_path(tmp_path / "data.h5")
    assert config_store.load_history(path) == []
