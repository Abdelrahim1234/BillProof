"""Persistence shared by REST, MCP, and admin commands.

Two logical databases are accessed only from the backend process:
``billproof_private`` (case-scoped, expiring data) and ``billproof_public``
(facilities, prices, glossary). REST routes, MCP tools, and scripts all go
through this module so they share one connection lifecycle (invariant 6).

``STORAGE_BACKEND=file`` (the default) keeps each database in a JSON file
under ``data/store/`` and exposes the small async collection surface the app
uses. ``STORAGE_BACKEND=mongodb`` wraps PyMongo's official AsyncMongoClient
with that same surface. Merely setting ``MONGODB_URI`` never changes the
backend, and tests are hard-pinned to the file store.

ponytail: one JSON file per database, reloaded on every collection access,
is simplest way to stay correct across process boundaries (the seed script,
the API process, and pytest's subprocess-spawning tests all observe the same
file) for a hackathon-scale demo. Use MongoDB when concurrent writers or file
size make the local store inappropriate.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from billproof.config import get_settings


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _comparable(actual: Any, val: Any) -> Any:
    """The file store round-trips plain datetimes through JSON as ISO
    strings (see _json_default); range comparisons need them back as
    datetimes. Pure in-memory (test) docs never hit this path."""
    if isinstance(val, datetime) and isinstance(actual, str):
        try:
            return datetime.fromisoformat(actual)
        except ValueError:
            return actual
    return actual


def _matches(doc: dict, flt: dict) -> bool:
    for key, expected in flt.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and any(k.startswith("$") for k in expected):
            for op, val in expected.items():
                if op == "$options":
                    continue  # a $regex modifier, not its own operator
                actual = _comparable(actual, val) if op in ("$gt", "$gte", "$lt", "$lte") else actual
                if op == "$in":
                    if actual not in val:
                        return False
                elif op == "$ne":
                    if actual == val:
                        return False
                elif op == "$gt":
                    if not (actual is not None and actual > val):
                        return False
                elif op == "$gte":
                    if not (actual is not None and actual >= val):
                        return False
                elif op == "$lt":
                    if not (actual is not None and actual < val):
                        return False
                elif op == "$lte":
                    if not (actual is not None and actual <= val):
                        return False
                elif op == "$exists":
                    if (actual is not None) != bool(val):
                        return False
                elif op == "$regex":
                    flags = re.IGNORECASE if "i" in expected.get("$options", "") else 0
                    if actual is None or not re.search(val, actual, flags):
                        return False
                else:
                    raise NotImplementedError(f"Unsupported store filter operator: {op}")
        else:
            if actual != expected:
                return False
    return True


def _project(doc: dict, projection: dict | None) -> dict:
    """Apply the small inclusion/exclusion projection subset admin tools use."""
    if not projection:
        return dict(doc)
    included = {key for key, enabled in projection.items() if enabled}
    excluded = {key for key, enabled in projection.items() if not enabled}
    if included:
        # MongoDB includes _id unless explicitly excluded.
        keys = included | ({"_id"} if projection.get("_id", 1) else set())
        return {key: doc[key] for key in keys if key in doc}
    return {key: value for key, value in doc.items() if key not in excluded}


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int = 1) -> _Cursor:
        self._docs = sorted(self._docs, key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction < 0)
        return self

    def limit(self, n: int) -> _Cursor:
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for d in self._docs:
            yield dict(d)

    async def to_list(self, length: int | None = None) -> list[dict]:
        docs = self._docs if length is None else self._docs[:length]
        return [dict(d) for d in docs]


class _Collection:
    def __init__(self, rows: list[dict], on_write, *, indexes: dict[str, dict] | None = None) -> None:
        self._rows = rows
        self._on_write = on_write
        self._indexes = indexes if indexes is not None else {}

    async def insert_one(self, doc: dict) -> Any:
        self._rows.append(dict(doc))
        self._on_write()
        return doc.get("_id")

    async def find_one(self, flt: dict, projection: dict | None = None) -> dict | None:
        for d in self._rows:
            if _matches(d, flt):
                return _project(d, projection)
        return None

    def find(self, flt: dict | None = None, projection: dict | None = None) -> _Cursor:
        flt = flt or {}
        return _Cursor([_project(d, projection) for d in self._rows if _matches(d, flt)])

    async def update_one(self, flt: dict, update: dict, upsert: bool = False) -> Any:
        for d in self._rows:
            if _matches(d, flt):
                d.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    d.pop(key, None)
                self._on_write()
                return d
        if upsert:
            new_doc = {**flt, **update.get("$set", {})}
            for key in update.get("$unset", {}):
                new_doc.pop(key, None)
            self._rows.append(new_doc)
            self._on_write()
            return new_doc
        return None

    async def delete_one(self, flt: dict) -> int:
        for i, d in enumerate(self._rows):
            if _matches(d, flt):
                del self._rows[i]
                self._on_write()
                return 1
        return 0

    async def delete_many(self, flt: dict) -> int:
        keep = [d for d in self._rows if not _matches(d, flt)]
        removed = len(self._rows) - len(keep)
        self._rows[:] = keep
        if removed:
            self._on_write()
        return removed

    async def count_documents(self, flt: dict | None = None) -> int:
        flt = flt or {}
        return sum(1 for d in self._rows if _matches(d, flt))

    async def create_index(self, keys, **kwargs) -> str:
        name = kwargs.get("name") or "_".join(f"{key}_{direction}" for key, direction in keys)
        self._indexes[name] = {"key": list(keys), **kwargs}
        return name  # metadata-only: the file store has no query planner

    async def index_information(self) -> dict[str, dict]:
        return {"_id_": {"key": [("_id", 1)]}, **self._indexes}

    async def distinct(self, key: str, flt: dict | None = None) -> list[Any]:
        values: list[Any] = []
        for doc in self._rows:
            if _matches(doc, flt or {}) and key in doc and doc[key] not in values:
                values.append(doc[key])
        return values


class _Database:
    """One logical database (private or public), backed by a JSON file so the
    seed script (a separate process), the API process, and pytest's own
    subprocess-spawning tests (test_map.py, test_seed.py, ...) all observe
    the same data. ``persist_path`` is unique per test session (see
    conftest.py's BILLPROOF_DB_DIR) so tests stay isolated from the real
    dev-mode file in data/store/.

    ponytail: reloads the whole file on every collection access rather than
    caching -- simplest way to stay correct across process boundaries for a
    hackathon-scale demo. Upgrade to real file locking (or a real database)
    if concurrent writers or file size ever make this measurably slow.
    """

    def __init__(self, persist_path: Path) -> None:
        self._persist_path = persist_path
        self._collections: dict[str, list[dict]] = {}
        self._indexes: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self) -> None:
        if self._persist_path.exists():
            try:
                self._collections = json.loads(self._persist_path.read_text())
            except (OSError, json.JSONDecodeError):
                self._collections = {}
        else:
            self._collections = {}

    def _flush(self) -> None:
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._persist_path.write_text(json.dumps(self._collections, default=_json_default))

    def __getitem__(self, name: str) -> _Collection:
        self._load()
        rows = self._collections.setdefault(name, [])
        return _Collection(rows, self._flush, indexes=self._indexes.setdefault(name, {}))

    async def list_collection_names(self) -> list[str]:
        self._load()
        return sorted(self._collections)

    async def command(self, name: str) -> dict:
        if name == "ping":
            return {"ok": 1}
        raise NotImplementedError(name)


class _Client:
    def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _MongoCollection:
    """Normalize PyMongo write results to the file-store interface."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def insert_one(self, doc: dict) -> Any:
        return (await self._collection.insert_one(doc)).inserted_id

    async def find_one(self, flt: dict, projection: dict | None = None) -> dict | None:
        return await self._collection.find_one(flt, projection)

    def find(self, flt: dict | None = None, projection: dict | None = None):
        return self._collection.find(flt or {}, projection)

    async def update_one(self, flt: dict, update: dict, upsert: bool = False) -> Any:
        return await self._collection.update_one(flt, update, upsert=upsert)

    async def delete_one(self, flt: dict) -> int:
        return (await self._collection.delete_one(flt)).deleted_count

    async def delete_many(self, flt: dict) -> int:
        return (await self._collection.delete_many(flt)).deleted_count

    async def count_documents(self, flt: dict | None = None) -> int:
        return await self._collection.count_documents(flt or {})

    async def create_index(self, keys, **kwargs) -> str:
        return await self._collection.create_index(keys, **kwargs)

    async def index_information(self) -> dict[str, dict]:
        return await self._collection.index_information()

    async def distinct(self, key: str, flt: dict | None = None) -> list[Any]:
        return await self._collection.distinct(key, flt or {})


class _MongoDatabase:
    def __init__(self, database: Any) -> None:
        self._database = database

    def __getitem__(self, name: str) -> _MongoCollection:
        return _MongoCollection(self._database[name])

    async def command(self, command: str | dict, *args, **kwargs) -> dict:
        return await self._database.command(command, *args, **kwargs)

    async def list_collection_names(self) -> list[str]:
        return sorted(await self._database.list_collection_names())


# --------------------------------------------------------------------------
# Connection state
# --------------------------------------------------------------------------

_client: Any = None
_private_db: Any = None
_public_db: Any = None
_private_path: Path | None = None
_public_path: Path | None = None
_backend: str | None = None
_target_id: str | None = None


def _data_dir() -> Path:
    """BILLPROOF_DB_DIR (set by tests/conftest.py to a per-session temp dir)
    isolates pytest runs from the real dev-mode state below."""
    override = os.environ.get("BILLPROOF_DB_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "data" / "store"


def _mongodb_hosts(uri: str) -> list[str]:
    """Return credential-free hostnames, solely for local/remote validation."""
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        raise RuntimeError("MONGODB_URI must use the mongodb:// or mongodb+srv:// scheme")
    authority = uri.split("://", 1)[1].split("/", 1)[0]
    host_list = authority.rsplit("@", 1)[-1]
    hosts: list[str] = []
    for item in host_list.split(","):
        parsed = urlsplit(f"//{item}")
        if not parsed.hostname:
            raise RuntimeError("MONGODB_URI does not contain a valid host")
        hosts.append(parsed.hostname.lower())
    return hosts


def _validate_mongodb_target(uri: str, *, allow_remote: bool, app_env: str) -> list[str]:
    hosts = _mongodb_hosts(uri)
    if app_env.lower() == "test" or os.environ.get("BILLPROOF_DB_DIR"):
        raise RuntimeError("Tests and BILLPROOF_DB_DIR are restricted to STORAGE_BACKEND=file")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if not allow_remote and any(host not in local_hosts for host in hosts):
        raise RuntimeError("Remote MongoDB requires MONGODB_ALLOW_REMOTE=true")
    return hosts


def _make_target_id(backend: str, public_name: str, private_name: str, authority: str) -> str:
    payload = f"{backend}\0{authority}\0{public_name}\0{private_name}".encode()
    return sha256(payload).hexdigest()[:20]


async def connect() -> None:
    """Connect exactly once to the explicitly selected storage backend."""
    global _backend, _client, _private_db, _private_path, _public_db, _public_path, _target_id
    if _client is not None:
        return
    settings = get_settings()
    if settings.storage_backend == "mongodb":
        if not settings.mongodb_uri:
            raise RuntimeError("STORAGE_BACKEND=mongodb requires MONGODB_URI")
        uri = settings.mongodb_uri.get_secret_value()
        hosts = _validate_mongodb_target(
            uri,
            allow_remote=settings.mongodb_allow_remote,
            app_env=settings.app_env,
        )
        # Lazy import keeps the default file store usable in minimal/offline
        # environments. Production installs PyMongo from pyproject.toml.
        from pymongo import AsyncMongoClient
        from pymongo.server_api import ServerApi

        client = AsyncMongoClient(
            uri,
            server_api=ServerApi("1"),
            serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
        )
        try:
            await client.admin.command({"ping": 1})
        except Exception:  # noqa: BLE001 -- replace driver detail with a credential-safe error
            await client.close()
            # Never interpolate the exception: driver errors can contain
            # connection target details and must not leak credentials.
            raise RuntimeError("MongoDB connection failed; verify server-only configuration") from None
        _client = client
        _private_db = _MongoDatabase(client[settings.mongodb_private_database])
        _public_db = _MongoDatabase(client[settings.mongodb_public_database])
        _private_path = None
        _public_path = None
        _backend = "mongodb"
        _target_id = _make_target_id(
            _backend,
            settings.mongodb_public_database,
            settings.mongodb_private_database,
            ",".join(sorted(hosts)),
        )
        return

    _client = _Client()
    data_dir = _data_dir()
    _private_path = data_dir / f"{settings.private_db_name}.json"
    _public_path = data_dir / f"{settings.public_db_name}.json"
    _private_db = _Database(_private_path)
    _public_db = _Database(_public_path)
    _backend = "file"
    _target_id = _make_target_id(
        _backend,
        settings.public_db_name,
        settings.private_db_name,
        str(data_dir.resolve()),
    )


async def close() -> None:
    global _backend, _client, _private_db, _public_db, _target_id
    if _client is not None:
        maybe = _client.close()
        if hasattr(maybe, "__await__"):
            await maybe
    _client = None
    _private_db = None
    _public_db = None
    _backend = None
    _target_id = None


def reset_state() -> None:
    """Test-only: wipes the store's on-disk state between tests."""
    global _private_db, _public_db
    if _backend != "file":
        raise RuntimeError("reset_state() is restricted to the file store")
    for path in (_private_path, _public_path):
        if path and path.exists():
            path.unlink()
    _private_db = _Database(_private_path)
    _public_db = _Database(_public_path)


def get_private_db():
    if _private_db is None:
        raise RuntimeError("store.connect() has not been called")
    return _private_db


def get_public_db():
    if _public_db is None:
        raise RuntimeError("store.connect() has not been called")
    return _public_db


def backend_name() -> str:
    if _backend is None:
        raise RuntimeError("store.connect() has not been called")
    return _backend


def target_id() -> str:
    """Credential-free fingerprint used to confirm admin-command targets."""
    if _target_id is None:
        raise RuntimeError("store.connect() has not been called")
    return _target_id


def logical_database_names() -> dict[str, str]:
    settings = get_settings()
    if backend_name() == "mongodb":
        return {
            "private": settings.mongodb_private_database,
            "public": settings.mongodb_public_database,
        }
    return {"private": settings.private_db_name, "public": settings.public_db_name}


async def health_check() -> dict:
    try:
        await get_private_db().command("ping")
        await get_public_db().command("ping")
        return {"status": "ok"}
    except Exception:  # noqa: BLE001 -- health check must never raise
        return {"status": "degraded"}


# --------------------------------------------------------------------------
# Idempotent index initializer (adapted to the collections this app actually
# persists -- indexes are a no-op against the file store, kept as executable
# documentation of the access patterns each collection needs to stay fast if
# this ever moves to a real database).
# --------------------------------------------------------------------------

PRIVATE_INDEXES: list[tuple[str, list[tuple[str, int]], dict]] = [
    # A parent-only MongoDB TTL can delete a case before the application has a
    # chance to cascade to its child collections. Keep this as a normal index;
    # schedule scripts/purge_expired_cases.py as the single cascade-safe owner.
    ("cases", [("expires_at", 1)], {"name": "cases_expires_at"}),
    ("cases", [("access_token_hash", 1)], {"name": "cases_access_token_hash", "unique": True}),
    ("bill_lines", [("case_id", 1)], {"name": "bill_lines_case_id"}),
    ("analyses", [("case_id", 1), ("created_at", -1)], {"name": "analyses_case_id_created_at"}),
    ("packets", [("case_id", 1), ("created_at", -1)], {"name": "packets_case_id_created_at"}),
    ("activity_receipts", [("case_id", 1)], {"name": "activity_receipts_case_id"}),
    ("case_evidence", [("case_id", 1)], {"name": "case_evidence_case_id"}),
    ("plan_benefit_profiles", [("case_id", 1)], {"name": "plan_benefit_profiles_case_id", "unique": True}),
    (
        "screen_submissions",
        [("room_code", 1), ("created_at", -1)],
        {"name": "screen_submissions_room_created_at"},
    ),
    (
        "screen_submissions",
        [("expires_at", 1)],
        {"name": "screen_submissions_expires_at_ttl", "expireAfterSeconds": 0},
    ),
]

PUBLIC_INDEXES: list[tuple[str, list[tuple[str, int]], dict]] = [
    ("facilities", [("facility_id", 1)], {"name": "facilities_facility_id", "unique": True, "sparse": True}),
    ("markets", [("market_id", 1)], {"name": "markets_market_id", "unique": True}),
    (
        "hospital_sources",
        [("hospital_id", 1), ("source_type", 1), ("active", 1)],
        {"name": "hospital_sources_hospital_type_active"},
    ),
    ("hospital_sources", [("sha256", 1)], {"name": "hospital_sources_sha256"}),
    (
        "price_records",
        [("hospital_id", 1), ("code_type", 1), ("code", 1), ("care_setting", 1), ("charge_type", 1)],
        {"name": "price_records_hospital_code_setting_charge"},
    ),
    (
        "price_records",
        [("payer_normalized", 1), ("plan_normalized", 1)],
        {"name": "price_records_payer_plan"},
    ),
    (
        "regional_benchmarks",
        [("geography_type", 1), ("geography_code", 1), ("service_code", 1), ("code_type", 1)],
        {"name": "regional_benchmarks_geo_code"},
    ),
    (
        "medicare_benchmarks",
        [("hospital_id", 1), ("code_type", 1), ("code", 1)],
        {"name": "medicare_benchmarks_hospital_code"},
    ),
    (
        "service_bundles",
        [("normalized_service_key", 1)],
        {"name": "service_bundles_normalized_key", "unique": True},
    ),
    ("facility_assistance", [("facility_id", 1)], {"name": "facility_assistance_facility_id"}),
    ("billing_glossary", [("slug", 1)], {"name": "billing_glossary_slug", "unique": True}),
]


async def init_indexes() -> dict[str, list[str]]:
    """Creates every index above if missing. Safe to run repeatedly; never
    drops, renames, or empties a collection."""
    created: dict[str, list[str]] = {"private": [], "public": []}
    for db, plan, bucket in ((get_private_db(), PRIVATE_INDEXES, "private"), (get_public_db(), PUBLIC_INDEXES, "public")):
        for collection, keys, options in plan:
            name = await db[collection].create_index(keys, **options)
            created[bucket].append(f"{collection}.{name or options.get('name')}")
    return created


def all_declared_collections() -> dict[str, Iterable[str]]:
    return {
        "private": sorted({c for c, _, _ in PRIVATE_INDEXES}),
        "public": sorted({c for c, _, _ in PUBLIC_INDEXES}),
    }
