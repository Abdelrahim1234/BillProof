from pathlib import Path

import pytest

from billproof import store
from billproof.config import Settings


def test_mongodb_uri_is_secret_and_does_not_select_backend() -> None:
    settings = Settings(_env_file=None, mongodb_uri="mongodb://user:secret@localhost:27017")

    assert settings.storage_backend == "file"
    assert "user:secret@" not in repr(settings)
    assert settings.mongodb_uri is not None
    assert settings.mongodb_uri.get_secret_value().endswith("@localhost:27017")


def test_remote_mongodb_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BILLPROOF_DB_DIR", raising=False)

    with pytest.raises(RuntimeError, match="MONGODB_ALLOW_REMOTE"):
        store._validate_mongodb_target(
            "mongodb+srv://user:password@example.mongodb.net/",
            allow_remote=False,
            app_env="development",
        )

    assert store._validate_mongodb_target(
        "mongodb+srv://user:password@example.mongodb.net/",
        allow_remote=True,
        app_env="development",
    ) == ["example.mongodb.net"]


def test_tests_cannot_select_mongodb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BILLPROOF_DB_DIR", raising=False)
    with pytest.raises(RuntimeError, match="restricted"):
        store._validate_mongodb_target(
            "mongodb://localhost:27017",
            allow_remote=False,
            app_env="test",
        )


def test_case_expiry_index_is_not_a_parent_only_ttl() -> None:
    case_indexes = [options for collection, _keys, options in store.PRIVATE_INDEXES if collection == "cases"]
    expiry = next(options for options in case_indexes if options["name"] == "cases_expires_at")
    assert "expireAfterSeconds" not in expiry


async def test_file_store_metadata_projection_and_unset() -> None:
    db = store.get_public_db()
    await db["metadata_test"].insert_one({"_id": "one", "keep": "yes", "remove": "no"})
    await db["metadata_test"].create_index([("keep", 1)], name="metadata_keep")

    projected = await db["metadata_test"].find_one({"_id": "one"}, {"keep": 1, "_id": 0})
    assert projected == {"keep": "yes"}
    assert await db.list_collection_names() == ["metadata_test"]
    assert "metadata_keep" in await db["metadata_test"].index_information()

    await db["metadata_test"].update_one({"_id": "one"}, {"$unset": {"remove": ""}})
    assert await db["metadata_test"].find_one({"_id": "one"}) == {"_id": "one", "keep": "yes"}
    assert store.backend_name() == "file"
    assert len(store.target_id()) == 20
    assert Path(store._data_dir()).exists()
