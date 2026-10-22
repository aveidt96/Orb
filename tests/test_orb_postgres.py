"""Postgres adapter tests use a SQL-recording driver and SQLite-backed double.

They exercise the Postgres application path without claiming a live Supabase
connection. The existing local tests exercise the same ledger rules directly.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
from contextlib import contextmanager

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from PIL import Image

from prometheus.api.app import create_app
from prometheus.api.orb_credits import CHAIN_ID, CreditConfig, CreditError, CreditService
from prometheus.api.orb_database import (
    DatabaseSession, OrbDatabase, POSTGRES_SCHEMA_V1, validate_postgres_url,
)


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class RecordingConnection:
    def __init__(self, versions=None, ledger=None):
        self.calls = []
        self.versions = versions or []
        self.ledger = ledger
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, parameters=()):
        self.calls.append((sql, parameters))
        if "SELECT version FROM orb.schema_versions" in sql:
            return FakeCursor(rows=[{"version": version} for version in self.versions])
        if "to_regclass" in sql:
            return FakeCursor(row={"ledger": self.ledger})
        return FakeCursor()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_postgres_url_requires_tls_and_never_echoes_credentials():
    validate_postgres_url("postgresql://orb:placeholder@db.example.invalid:5432/orb?sslmode=require")
    validate_postgres_url("postgres://orb:placeholder@db.example.invalid/orb")
    for invalid in ("sqlite:///tmp/ledger.db", "postgresql://db.example.invalid",
                    "postgresql://db.example.invalid/orb?sslmode=disable",
                    "postgresql://db.example.invalid:bad/orb"):
        with pytest.raises(ValueError) as error:
            validate_postgres_url(invalid)
        assert "placeholder" not in str(error.value)


def test_postgres_schema_is_versioned_non_destructive_and_transactional(monkeypatch):
    store = OrbDatabase.__new__(OrbDatabase)
    connection = RecordingConnection()
    monkeypatch.setattr(store, "_connect_postgres", lambda: connection)
    store._initialize_postgres()
    statements = [sql for sql, _ in connection.calls]
    assert connection.committed and connection.closed and not connection.rolled_back
    assert any("pg_advisory_xact_lock" in sql for sql in statements)
    assert any("INSERT INTO orb.schema_versions" in sql for sql in statements)
    assert all(not sql.lstrip().upper().startswith("DROP ") for sql in statements)
    assert any("CREATE TABLE orb.results" in sql and "JSONB" in sql for sql in POSTGRES_SCHEMA_V1)
    assert any("UNIQUE (wallet, idem_key)" in sql for sql in POSTGRES_SCHEMA_V1)
    assert any("CHECK (granted >= consumed + reserved)" in sql for sql in POSTGRES_SCHEMA_V1)
    assert any("quote_id TEXT NOT NULL UNIQUE REFERENCES orb.quotes" in sql for sql in POSTGRES_SCHEMA_V1)

    existing = RecordingConnection(versions=[1])
    monkeypatch.setattr(store, "_connect_postgres", lambda: existing)
    store._initialize_postgres()
    assert not any(sql in POSTGRES_SCHEMA_V1 for sql, _ in existing.calls)

    unversioned = RecordingConnection(ledger="orb.balances")
    monkeypatch.setattr(store, "_connect_postgres", lambda: unversioned)
    with pytest.raises(RuntimeError, match="unversioned"):
        store._initialize_postgres()
    assert unversioned.rolled_back


def test_postgres_session_translates_parameters_and_uses_row_transactions():
    connection = RecordingConnection()
    session = DatabaseSession(connection, postgres=True)
    session.begin_write()
    session.execute("INSERT INTO results(payload) VALUES (?::jsonb)", ('{"prompt":"ready"}',))
    assert connection.calls == [("INSERT INTO results(payload) VALUES (%s::jsonb)",
                                 ('{"prompt":"ready"}',))]
    session.commit()
    assert connection.committed


class FakeChain:
    def __init__(self, receiver):
        self.receiver = receiver
        self.quote = None
        self.wallet = None

    def call(self, method, params):
        block_hash = "0x" + "cd" * 32
        tx_hash = "0x" + "ab" * 32
        quote = self.quote
        values = {
            "eth_chainId": hex(CHAIN_ID),
            "eth_getTransactionReceipt": {
                "transactionHash": tx_hash, "status": "0x1", "from": self.wallet,
                "to": self.receiver, "blockHash": block_hash, "blockNumber": "0x64",
            },
            "eth_getTransactionByHash": {
                "hash": tx_hash, "from": self.wallet, "to": self.receiver,
                "value": hex(int(quote["value_wei"])), "input": quote["data"],
                "blockHash": block_hash, "chainId": hex(CHAIN_ID),
            },
            "eth_blockNumber": "0x66",
            "eth_getBlockByNumber": {"hash": block_hash, "timestamp": hex(int(time.time()))},
            "eth_getCode": "0x",
        }
        return values[method]


class SqliteBackedPostgresDouble:
    """Runs Postgres application statements against isolated SQLite in tests."""

    postgres = True

    def __init__(self, local):
        self.local = local
        with local.session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS results (
                job_id TEXT PRIMARY KEY REFERENCES reservations(job_id),
                payload TEXT NOT NULL, created_at INTEGER NOT NULL
            )""")

    @contextmanager
    def session(self):
        with self.local.session() as db:
            yield PostgresStatementDouble(db)


class PostgresStatementDouble:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        return self.db.execute(sql.replace(" FOR UPDATE", "").replace("?::jsonb", "?"), params)

    def begin_write(self):
        self.db.begin_write()

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()


def make_store(tmp_path):
    wallet = Account.create()
    receiver = Account.create().address
    chain = FakeChain(receiver)
    config = CreditConfig(database=tmp_path / "mock-postgres.sqlite3",
                          public_origin="http://localhost",
                          rpc_url="https://rpc.example.invalid", receiver=receiver,
                          enabled=True, price_wei=1000, confirmations=3)
    service = CreditService(config, chain)
    service.database = SqliteBackedPostgresDouble(service.database)
    chain.wallet = wallet.address
    return service, wallet, chain


def purchase_one(service, wallet, chain):
    quote = service.create_quote(wallet.address.lower(), 1)
    chain.quote = quote
    tx_hash = "0x" + "ab" * 32
    assert service.verify_purchase(wallet.address.lower(), quote["quote_id"], tx_hash)["balance"]["available"] == 1
    with pytest.raises(CreditError, match="already been credited"):
        second = service.create_quote(wallet.address.lower(), 1)
        chain.quote = second
        service.verify_purchase(wallet.address.lower(), second["quote_id"], tx_hash)


def test_mocked_postgres_logout_revokes_current_session(tmp_path):
    service, wallet, _ = make_store(tmp_path)
    challenge = service.challenge(wallet.address, "http://localhost")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    signed = service.sign_in(challenge["nonce"], signature, "http://localhost")
    bearer = "Bearer " + signed["token"]
    assert service.authenticate(bearer) == wallet.address.lower()
    service.logout(bearer)
    with pytest.raises(CreditError) as expired:
        service.authenticate(bearer)
    assert expired.value.status == 401


def test_mocked_postgres_result_survives_restart_and_settles_once(tmp_path):
    service, wallet, chain = make_store(tmp_path)
    purchase_one(service, wallet, chain)
    address = wallet.address.lower()

    def reserve(index):
        try:
            return service.reserve(address, "enhance", f"key-{index:032d}", "fingerprint", f"job-{index}")
        except CreditError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(reserve, range(6)))
    assert len([item for item in outcomes if isinstance(item, tuple)]) == 1
    assert outcomes.count(402) == 5
    winner_index, winner = next((index, item) for index, item in enumerate(outcomes)
                                if isinstance(item, tuple))
    job_id = winner[0]
    assert service.reserve(address, "enhance", f"key-{winner_index:032d}",
                           "fingerprint", "duplicate") == (job_id, False)

    payload = {"job_id": job_id, "prompt": "A real stored prompt", "operation": "enhance"}
    service.save_result(job_id, payload, tmp_path / "ephemeral")
    assert service.result(job_id, tmp_path / "missing") == payload
    restarted = CreditService(service.config, chain)
    restarted.database = SqliteBackedPostgresDouble(restarted.database)
    restarted.reconcile(tmp_path / "ephemeral-gone")
    assert restarted.balance(address)["consumed"] == 1
    assert restarted.balance(address)["available"] == 0
    assert restarted.result(job_id, tmp_path / "ephemeral-gone") == payload
    restarted.reconcile(tmp_path / "ephemeral-gone")
    assert restarted.balance(address)["consumed"] == 1


def test_mocked_postgres_failed_job_releases_credit_after_restart(tmp_path):
    service, wallet, chain = make_store(tmp_path)
    purchase_one(service, wallet, chain)
    address = wallet.address.lower()
    service.reserve(address, "decode", "r" * 32, "fingerprint", "failed-job")
    restarted = CreditService(service.config, chain)
    restarted.database = SqliteBackedPostgresDouble(restarted.database)
    restarted.reconcile(tmp_path / "ephemeral-gone")
    assert restarted.balance(address)["available"] == 1
    assert restarted.balance(address)["reserved"] == 0
    assert restarted.balance(address)["consumed"] == 0



def test_mocked_production_api_result_recovers_without_local_files(monkeypatch, tmp_path):
    service, wallet, chain = make_store(tmp_path)
    postgres_url = "postgresql://orb:placeholder@db.example.invalid:5432/orb?sslmode=require"
    service.config = replace(service.config, public_origin="https://orb.example",
                             database_url=postgres_url)
    purchase_one(service, wallet, chain)
    challenge = service.challenge(wallet.address, "https://orb.example")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    token = service.sign_in(challenge["nonce"], signature, "https://orb.example")["token"]
    headers = {"Origin": "https://orb.example", "Authorization": "Bearer " + token,
               "X-Orb-Idempotency-Key": "mock-postgres-decode-000001"}

    values = {
        "ORB_ENV": "production", "ORB_AI_LOCAL_TESTING": "0", "ORB_CREDITS_ENABLED": "1",
        "ORB_AI_PROVIDER": "gemini", "ORB_AI_MODEL": "test-model",
        "GEMINI_API_KEY": "test-only-placeholder", "ORB_PUBLIC_ORIGIN": "https://orb.example",
        "ORB_DATABASE_URL": postgres_url, "ORB_UPLOAD_DIR": str(tmp_path / "uploads"),
        "ORB_ARBITRUM_RPC_URL": "https://rpc.example.invalid",
        "ORB_CREDIT_RECEIVER": service.config.receiver,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in ("PROMETHEUS_PROVIDER", "PROMETHEUS_API_KEY", "PROMETHEUS_FFMPEG_DIR",
                 "PROMETHEUS_API_OUTPUT_DIR", "PROMETHEUS_API_UPLOAD_DIR",
                 "ORB_ENABLE_NIMIQ_PAYMENTS"):
        monkeypatch.delenv(name, raising=False)

    class FakeAI:
        def image(self, operation, source):
            return {"prompt": "A blue reference image", "visual_analysis": {
                "subject_and_scene": "A blue square"}, "refinements": []}

    image = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
    scratch = tmp_path / "scratch"
    app = create_app(provider="gemini", output_dir=scratch, upload_dir=tmp_path / "uploads",
                     orb_ai_service=FakeAI(), orb_credit_service=service)
    with TestClient(app) as client:
        accepted = client.post("/api/orb/decode/file", headers=headers,
                               files={"file": ("sample.png", image.getvalue(), "image/png")})
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        deadline = time.monotonic() + 15
        while True:
            status = client.get(f"/api/jobs/{job_id}", headers=headers).json()
            if status["state"] != "processing" or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        assert status["state"] == "complete"
        result = client.get(f"/api/jobs/{job_id}/result", headers=headers).json()
        assert result["prompt"] == "A blue reference image"
        assert "preview_url" not in result["image"]
        assert service.balance(wallet.address.lower())["consumed"] == 1
        # Completion makes the durable result available before the worker's
        # finally block removes scratch artifacts. Wait for that cleanup too.
        cleanup_deadline = time.monotonic() + 5
        while (scratch / job_id).exists() and time.monotonic() < cleanup_deadline:
            time.sleep(.01)
        assert not (scratch / job_id).exists()

    restarted = CreditService(replace(service.config, database_url=""), chain)
    restarted.database = SqliteBackedPostgresDouble(restarted.database)
    restarted.config = service.config
    resumed = create_app(provider="gemini", output_dir=scratch, upload_dir=tmp_path / "uploads",
                         orb_ai_service=FakeAI(), orb_credit_service=restarted)
    with TestClient(resumed) as client:
        assert client.get(f"/api/jobs/{job_id}", headers=headers).json()["state"] == "complete"
        recovered = client.get(f"/api/jobs/{job_id}/result", headers=headers).json()
        assert recovered["prompt"] == "A blue reference image"
        assert restarted.balance(wallet.address.lower())["consumed"] == 1
