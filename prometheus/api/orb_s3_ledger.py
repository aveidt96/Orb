"""Small testnet ledger: atomic S3 snapshots, never best-effort wallet backups.

All wallets, quotes, accepted tx hashes, sessions, reservations and results share
one conditional-write boundary. For larger workloads use the Postgres adapter.
S3 errors fail closed; no stale local fallback or unconditional overwrite.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from functools import wraps
import random
import time

from botocore.config import Config
from botocore.exceptions import ClientError

from prometheus.api.orb_database import DatabaseSession, OrbDatabase, SQLITE_SCHEMA

LEDGER_KEY = "orb-credits/ledger-v1.sqlite3"
MAX_BYTES = 16 * 1024 * 1024


class LedgerUnavailable(Exception):
    pass


class LedgerConflict(LedgerUnavailable):
    pass


def retry_ledger_conflicts(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        for attempt in range(8):
            try:
                return method(*args, **kwargs)
            except LedgerConflict:
                if attempt == 7:
                    # Imported lazily to avoid the CreditService import cycle.
                    from prometheus.api.orb_credits import CreditError
                    raise CreditError("Credit service is busy. Retry the same request.", 409) from None
                time.sleep(random.uniform(0.01, 0.04) * (attempt + 1))
    return wrapped


class S3LedgerSession(DatabaseSession):
    def __init__(self, connection, ledger, etag):
        super().__init__(connection, False)
        self.ledger, self.etag = ledger, etag
        self.saved_changes = connection.total_changes

    def commit(self):
        self.connection.commit()
        if self.connection.total_changes != self.saved_changes:
            # Publication must succeed before callers receive a successful grant
            # or reservation. CAS conflicts discard this private snapshot.
            self.etag = self.ledger.publish(self.connection.serialize(), self.etag)
            self.saved_changes = self.connection.total_changes


class S3LedgerDatabase:
    postgres = False
    s3 = True

    def __init__(self, bucket, client=None, *, usdg=False):
        if not bucket:
            raise LedgerUnavailable("An S3 ledger bucket is required.")
        if client is None:
            import boto3
            client = boto3.client("s3", config=Config(connect_timeout=4, read_timeout=8,
                                  retries={"max_attempts": 0}))
        self.bucket, self.client, self.usdg = bucket, client, usdg

    def publish(self, data, etag=None):
        if len(data) > MAX_BYTES:
            raise LedgerUnavailable("Credit ledger requires Postgres migration.")
        try:
            result = self.client.put_object(Bucket=self.bucket, Key=LEDGER_KEY, Body=data,
                ContentType="application/vnd.sqlite3", ServerSideEncryption="AES256",
                **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}))
            return result["ETag"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}:
                raise LedgerConflict("Concurrent ledger update.") from None
            raise LedgerUnavailable("Durable credit storage is unavailable.") from None
        except Exception:
            raise LedgerUnavailable("Durable credit storage is unavailable.") from None

    def bootstrap(self):
        """Explicit deployment step; application startup never creates/resets it."""
        try:
            with self.session():
                return False
        except LedgerUnavailable as exc:
            if str(exc) != "Credit ledger is not initialized.":
                raise
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(SQLITE_SCHEMA)
            # The shared result table is added only to this new S3 ledger.
            connection.execute("CREATE TABLE results (job_id TEXT PRIMARY KEY REFERENCES reservations(job_id), payload TEXT NOT NULL, created_at INTEGER NOT NULL)")
            OrbDatabase._create_usdg(connection, False)
            connection.execute("PRAGMA user_version=1")
            connection.commit()
            try:
                self.publish(connection.serialize())
                return True
            except LedgerConflict:
                # Another explicit bootstrap won. Verify rather than overwrite.
                with self.session():
                    return False
        finally:
            connection.close()

    @contextmanager
    def session(self):
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=LEDGER_KEY)
            stream = obj["Body"]
            try:
                data = stream.read(MAX_BYTES + 1)
            finally:
                stream.close()
            if len(data) > MAX_BYTES or not data.startswith(b"SQLite format 3\x00"):
                raise LedgerUnavailable("Invalid durable credit ledger.")
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                raise LedgerUnavailable("Credit ledger is not initialized.") from None
            raise LedgerUnavailable("Durable credit storage is unavailable.") from None
        except LedgerUnavailable:
            raise
        except Exception:
            raise LedgerUnavailable("Durable credit storage is unavailable.") from None
        connection = sqlite3.connect(":memory:", isolation_level=None)
        try:
            connection.deserialize(data)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise LedgerUnavailable("Unsupported durable credit ledger version.")
            session = S3LedgerSession(connection, self, obj["ETag"])
            yield session
            session.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
