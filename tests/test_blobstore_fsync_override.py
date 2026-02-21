import inspect


def test_encrypted_blobstore_put_new_accepts_fsync_policy_kwarg() -> None:
    from plugins.builtin.storage_encrypted.plugin import EncryptedBlobStore

    params = inspect.signature(EncryptedBlobStore.put_new).parameters
    assert "fsync_policy" in params


def test_plain_blobstore_put_new_accepts_fsync_policy_kwarg() -> None:
    from plugins.builtin.storage_sqlcipher.plugin import PlainBlobStore

    params = inspect.signature(PlainBlobStore.put_new).parameters
    assert "fsync_policy" in params

