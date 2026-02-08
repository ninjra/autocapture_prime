from pathlib import Path


def test_backup_create_and_restore_archives_conflicts(tmp_path, monkeypatch):
    # Fake a repo root so backup/restore doesn't touch the real repo.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[build-system]\nrequires=[]\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "data_anchor").mkdir()
    lockfile = repo / "config" / "plugin_locks.json"
    lockfile.write_text('{"locks": []}\n', encoding="utf-8")
    anchors = repo / "data_anchor" / "anchors.ndjson"
    anchors.write_text('{"ts":"t","h":"x"}\n', encoding="utf-8")

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    user_cfg = config_dir / "user.json"
    user_cfg.write_text('{"paths": {"data_dir": "DATA"}}\n', encoding="utf-8")

    data_dir = tmp_path / "data"
    (data_dir / "vault").mkdir(parents=True)
    (data_dir / "ledger.ndjson").write_text('{"h":"a"}\n', encoding="utf-8")
    (data_dir / "journal.ndjson").write_text('{"t":"j"}\n', encoding="utf-8")

    # Make repo_root() resolve to our fake repo for any indirect calls.
    monkeypatch.setenv("AUTOCAPTURE_ROOT", str(repo))

    from autocapture_nx.kernel.backup_bundle import create_backup_bundle, restore_backup_bundle

    bundle = tmp_path / "bundle.zip"
    report = create_backup_bundle(
        output_path=bundle,
        repo=repo,
        config_dir=config_dir,
        data_dir=data_dir,
        include_data=False,
        include_keyring_bundle=True,
        keyring_bundle_passphrase="pw",
        keyring_backend="portable",
        keyring_credential_name="autocapture.keyring",
        require_key_protection=False,
        overwrite=False,
    )
    assert report["ok"] is True
    assert bundle.exists()

    # Mutate files to ensure restore archives and replaces them.
    lockfile.write_text('{"locks": ["changed"]}\n', encoding="utf-8")
    user_cfg.write_text('{"changed": true}\n', encoding="utf-8")
    (data_dir / "ledger.ndjson").write_text('{"h":"changed"}\n', encoding="utf-8")
    # Ensure a keyring file exists so restore has a conflict to archive.
    keyring_path = data_dir / "vault" / "keyring.json"
    keyring_path.write_text('{"schema_version": 2, "purposes": {}}\n', encoding="utf-8")

    restore = restore_backup_bundle(
        bundle_path=bundle,
        repo=repo,
        config_dir=config_dir,
        data_dir=data_dir,
        keyring_bundle_passphrase="pw",
        restore_keyring_bundle=True,
        overwrite=False,
    )
    assert restore["ok"] is True
    assert restore["extracted"] >= 3
    assert any("plugin_locks.json.bak." in p for p in restore["archived"])
    assert any("user.json.bak." in p for p in restore["archived"])
    assert any("keyring.json.bak." in p for p in restore["archived"])

    # Restored content matches the original backup inputs.
    assert lockfile.read_text(encoding="utf-8") == '{"locks": []}\n'
    assert user_cfg.read_text(encoding="utf-8") == '{"paths": {"data_dir": "DATA"}}\n'
    assert (data_dir / "ledger.ndjson").read_text(encoding="utf-8") == '{"h":"a"}\n'
