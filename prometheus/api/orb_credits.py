"""Orb-only Arbitrum Sepolia wallet authentication and credit ledger.

Native testnet ETH remains the default. Explicit enabled methods can add the
Paxos token's direct ERC-20 transfer to the configured EOA. Quotes bind
the exact amounts and input; the server independently verifies receipts.
No signing key or payment secret is held by Orb.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from eth_utils import is_address, to_checksum_address

from prometheus.api.orb_database import OrbDatabase
from prometheus.api.orb_usdg import USDG_CONTRACT, USDG_DECIMALS, USDG_PRICE, matching_transfer, transfer_data


CHAIN_ID = 421614
CHAIN_HEX = hex(CHAIN_ID)
TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
QUOTE_DATA_PREFIX = "0x4f524231"  # ASCII ORB1 + random quote id bytes
JUDGE_WALLET_PREFIX = "0x4a75646765"  # ASCII "Judge" prefix in 20-byte address


def is_judge_wallet(wallet: str | None) -> bool:
    return isinstance(wallet, str) and wallet.lower().startswith(JUDGE_WALLET_PREFIX)


class CreditError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CreditConfig:
    database: Path
    database_url: str = ""
    public_origin: str = ""
    rpc_url: str = ""
    receiver: str = ""
    price_wei: int = 1_000_000_000_000  # 0.000001 testnet ETH per credit
    confirmations: int = 3
    enabled: bool = False
    payment_method: str = "native"
    payment_methods: tuple[str, ...] = ()
    chain_id: int = CHAIN_ID
    usdg_contract: str = USDG_CONTRACT
    usdg_decimals: int = USDG_DECIMALS
    usdg_price: int = USDG_PRICE
    deployment_target: str = ""
    judge_demo_code: str = ""
    judge_daily_cap: int = 150
    judge_ip_daily_limit: int = 3
    judge_session_credits: int = 10

    def __post_init__(self) -> None:
        if (self.payment_method not in {"native", "native_eth", "usdg"} or self.chain_id != CHAIN_ID
                or any(method not in {"native_eth", "usdg"} for method in self.payment_methods)
                or len(set(self.payment_methods)) != len(self.payment_methods)):
            raise ValueError("Orb payments require Arbitrum Sepolia and a supported payment method.")
        if "usdg" in self.methods:
            if ((not self.payment_methods and self.deployment_target != "usdg-staging")
                    or self.usdg_contract.lower() != USDG_CONTRACT.lower()
                    or self.usdg_decimals != USDG_DECIMALS
                    or self.receiver.lower() == USDG_CONTRACT.lower()
                    or (self.deployment_target == "usdg-staging"
                        and self.public_origin.rstrip("/") == "https://orb-azure-ten.vercel.app")):
                raise ValueError("USDG requires explicit payment methods or the isolated staging target, and exact Paxos Sepolia token configuration.")
            if type(self.usdg_price) is not int or self.usdg_price <= 0:
                raise ValueError("USDG credit price must be a positive integer in base units.")
        if self.price_wei <= 0 or not 1 <= self.confirmations <= 100:
            raise ValueError("Invalid Orb testnet credit price or confirmation count.")
        if (type(self.judge_daily_cap) is not int or self.judge_daily_cap <= 0
                or type(self.judge_ip_daily_limit) is not int or self.judge_ip_daily_limit <= 0
                or type(self.judge_session_credits) is not int or not 1 <= self.judge_session_credits <= 100):
            raise ValueError("Invalid Judge Demo Mode limits.")
        if self.enabled:
            origin = urlparse(self.public_origin)
            rpc = urlparse(self.rpc_url)
            if (not origin.scheme or not origin.netloc or origin.path not in {"", "/"}
                    or origin.query or origin.fragment
                    or (origin.scheme != "https" and origin.hostname not in {"localhost", "127.0.0.1"})
                    or rpc.scheme != "https" or not rpc.netloc or not is_address(self.receiver)):
                raise ValueError("Orb credit configuration requires a trusted origin, HTTPS RPC, and receiver address.")

    @property
    def methods(self) -> tuple[str, ...]:
        return self.payment_methods or (("usdg",) if self.payment_method == "usdg" else ("native_eth",))

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.public_origin and self.rpc_url and self.receiver)

    @property
    def judge_ready(self) -> bool:
        return bool(isinstance(self.judge_demo_code, str) and self.judge_demo_code.strip())


class RpcClient:
    def __init__(self, url: str):
        self.url = url

    def call(self, method: str, params: list) -> object:
        try:
            response = requests.post(self.url, json={"jsonrpc": "2.0", "id": 1,
                                                     "method": method, "params": params}, timeout=12)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or "error" in body or "result" not in body:
                raise ValueError("RPC returned an error")
            return body["result"]
        except (requests.RequestException, ValueError) as exc:
            raise CreditError("Arbitrum Sepolia RPC is unavailable. Try verification again later.", 503) from exc


class CreditService:
    def __init__(self, config: CreditConfig, rpc: RpcClient | None = None):
        self.config = config
        self.rpc = rpc or RpcClient(config.rpc_url)
        self.database = OrbDatabase(config.database, config.database_url, usdg_staging="usdg" in config.methods)

    def _db(self):
        return self.database.session()

    def _lock(self) -> str:
        return " FOR UPDATE" if self.database.postgres else ""

    def _require_ready(self) -> None:
        if not self.config.ready:
            raise CreditError("Arbitrum Sepolia testnet credits are not configured.", 503)

    def challenge(self, address: str, origin: str) -> dict:
        self._require_ready()
        self._check_origin(origin)
        if not is_address(address):
            raise CreditError("Enter a valid wallet address.")
        wallet = to_checksum_address(address)
        nonce = secrets.token_hex(16)
        issued = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        expiry = datetime.fromtimestamp(time.time() + 300, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        parsed = urlparse(self.config.public_origin)
        message = (f"{parsed.netloc} wants you to sign in with your Ethereum account:\n{wallet}\n\n"
                   "Sign in to Orb's Arbitrum Sepolia testnet demo.\n\n"
                   f"URI: {self.config.public_origin}\nVersion: 1\nChain ID: {CHAIN_ID}\n"
                   f"Nonce: {nonce}\nIssued At: {issued}\nExpiration Time: {expiry}")
        with self._db() as db:
            db.execute("INSERT INTO challenges VALUES (?, ?, ?, ?, 0)",
                       (nonce, wallet.lower(), message, int(time.time()) + 300))
        return {"nonce": nonce, "message": message, "expires_at": expiry}

    def sign_in(self, nonce: str, signature: str, origin: str) -> dict:
        self._require_ready()
        self._check_origin(origin)
        if not isinstance(nonce, str) or not isinstance(signature, str) or len(signature) > 256:
            raise CreditError("Invalid wallet signature.", 401)
        with self._db() as db:
            db.begin_write()
            row = db.execute("SELECT * FROM challenges WHERE nonce=?" + self._lock(), (nonce,)).fetchone()
            if row is None or row["used"] or row["expires"] < time.time():
                raise CreditError("Sign-in challenge expired or already used.", 401)
            try:
                signer = Account.recover_message(encode_defunct(text=row["message"]), signature=signature)
            except (ValueError, TypeError, BadSignature) as exc:
                raise CreditError("Invalid wallet signature.", 401) from exc
            if signer.lower() != row["wallet"]:
                raise CreditError("Signature does not match the requested wallet.", 401)
            db.execute("UPDATE challenges SET used=1 WHERE nonce=?", (nonce,))
            token = secrets.token_urlsafe(32)
            expires = int(time.time()) + 3600
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), row["wallet"], expires))
            db.execute("INSERT INTO balances(wallet) VALUES (?) ON CONFLICT DO NOTHING", (row["wallet"],))
            db.commit()
        return {"token": token, "wallet": to_checksum_address(row["wallet"]), "expires_at": expires}

    def authenticate(self, authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise CreditError("Connect and sign with your wallet first.", 401)
        token = authorization[7:]
        if not 32 <= len(token) <= 128:
            raise CreditError("Wallet session is invalid.", 401)
        with self._db() as db:
            row = db.execute("SELECT wallet, expires FROM sessions WHERE token_hash=?",
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None or row["expires"] <= time.time():
            raise CreditError("Wallet session expired. Sign again.", 401)
        return row["wallet"]

    def logout(self, authorization: str | None) -> None:
        """Revoke this signed Orb session without changing credits or wallet permissions."""
        wallet = self.authenticate(authorization)
        token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=? AND wallet=?", (token_hash, wallet))

    def _check_origin(self, origin: str | None) -> None:
        if origin != self.config.public_origin:
            raise CreditError("Wallet request origin is not trusted.", 403)

    def create_judge_session(self, code: str, client_ip: str, origin: str | None = None) -> dict:
        if not self.config.judge_ready:
            raise CreditError("Judge Demo Mode is not enabled on this server.", 503)
        if origin is not None and self.config.public_origin:
            self._check_origin(origin)
        candidate = code.strip() if isinstance(code, str) else ""
        expected = self.config.judge_demo_code.strip()
        if not candidate or len(candidate) > 256 or not hmac.compare_digest(
            candidate.encode("utf-8"), expected.encode("utf-8")
        ):
            raise CreditError("Invalid Judge Demo access code.", 401)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        ip_key = (client_ip or "unknown").strip().lower()
        ip_marker = f"judge-ip:{day}:{hashlib.sha256(f'{day}:{ip_key}'.encode()).hexdigest()[:32]}"
        day_prefix = f"{JUDGE_WALLET_PREFIX}{day}%"
        with self._db() as db:
            db.begin_write()
            if self.database.postgres:
                db.execute("SELECT pg_advisory_xact_lock(749519622)")
            ip_row = db.execute("SELECT COUNT(*) AS cnt FROM challenges WHERE message=?", (ip_marker,)).fetchone()
            ip_count = int((ip_row["cnt"] if ip_row else 0) or 0)
            if ip_count >= self.config.judge_ip_daily_limit:
                raise CreditError("Daily Judge Demo session limit reached for this network.", 429)
            usage = db.execute(
                "SELECT COALESCE(SUM(consumed + reserved), 0) AS used, COUNT(*) AS sessions "
                "FROM balances WHERE wallet LIKE ?",
                (day_prefix,),
            ).fetchone()
            used_today = int((usage["used"] if usage else 0) or 0)
            sessions_today = int((usage["sessions"] if usage else 0) or 0)
            if used_today >= self.config.judge_daily_cap or sessions_today >= self.config.judge_daily_cap:
                raise CreditError(
                    "Daily Judge Demo Mode capacity reached. Try again tomorrow or connect an Arbitrum Sepolia wallet.",
                    429,
                )
            credits = min(self.config.judge_session_credits, self.config.judge_daily_cap - used_today)
            wallet = f"{JUDGE_WALLET_PREFIX}{day}{secrets.token_hex(11)}"
            token = secrets.token_urlsafe(32)
            expires = int(time.time()) + 3600
            nonce = f"judge:{day}:{secrets.token_hex(12)}"
            db.execute("INSERT INTO challenges VALUES (?, ?, ?, ?, 1)", (nonce, wallet, ip_marker, expires))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), wallet, expires))
            db.execute("INSERT INTO balances(wallet, granted, consumed, reserved) VALUES (?, ?, 0, 0)",
                       (wallet, credits))
            db.commit()
        checksum = to_checksum_address(wallet)
        return {
            "token": token,
            "wallet": checksum,
            "expires_at": expires,
            "credits": credits,
            "judge_demo": True,
            "balance": {
                "wallet": checksum,
                "available": credits,
                "reserved": 0,
                "consumed": 0,
                "granted": credits,
                "judge_demo": True,
            },
        }

    def balance(self, wallet: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT granted, consumed, reserved FROM balances WHERE wallet=?",
                             (wallet,)).fetchone()
        granted, consumed, reserved = (row["granted"], row["consumed"], row["reserved"]) if row else (0, 0, 0)
        result = {"wallet": to_checksum_address(wallet), "available": granted - consumed - reserved,
                  "reserved": reserved, "consumed": consumed, "granted": granted}
        if is_judge_wallet(wallet):
            result["judge_demo"] = True
        return result

    def create_quote(self, wallet: str, credits: int, payment_method: str | None = None) -> dict:
        if is_judge_wallet(wallet):
            raise CreditError("Judge Demo sessions cannot purchase testnet credits.", 403)
        self._require_ready()
        if payment_method is None:
            if len(self.config.methods) != 1:
                raise CreditError("Choose a payment method.")
            payment_method = self.config.methods[0]
        if not isinstance(payment_method, str) or payment_method not in {"native_eth", "usdg"}:
            raise CreditError("Invalid payment method.")
        if payment_method not in self.config.methods:
            raise CreditError("This payment method is not enabled.")
        if type(credits) is not int or credits not in {1, 3, 5}:
            raise CreditError("Choose 1, 3, or 5 testnet credits.")
        quote_id = secrets.token_hex(16)
        tx_data = QUOTE_DATA_PREFIX + quote_id
        created = int(time.time())
        expires = created + 900
        usdg = payment_method == "usdg"
        amount = (self.config.usdg_price if usdg else self.config.price_wei) * credits
        if usdg:
            try:
                if int(self.rpc.call("eth_chainId", []), 16) != CHAIN_ID:
                    raise CreditError("RPC is connected to the wrong network.", 503)
                created_block = int(self.rpc.call("eth_blockNumber", []), 16)
                if created_block < 0:
                    raise ValueError("Invalid block height")
            except (ValueError, TypeError) as exc:
                raise CreditError("RPC returned incomplete quote details.", 503) from exc
            tx_data = transfer_data(self.config.receiver, amount)
        with self._db() as db:
            db.begin_write()
            db.execute("INSERT INTO quotes VALUES (?, ?, ?, ?, ?, ?, NULL)",
                       (quote_id, wallet, credits, amount, tx_data, expires))
            if usdg:
                db.execute("INSERT INTO usdg_quotes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (quote_id, CHAIN_ID, self.config.usdg_contract.lower(), USDG_DECIMALS,
                            self.config.receiver.lower(), amount, created, created_block))
        if usdg:
            return {"quote_id": quote_id, "wallet": to_checksum_address(wallet), "chain_id": CHAIN_ID,
                    "payment_method": "usdg", "token_symbol": "USDG", "token_decimals": USDG_DECIMALS,
                    "token_contract": to_checksum_address(self.config.usdg_contract),
                    "receiver": to_checksum_address(self.config.receiver), "amount_base_units": str(amount),
                    "to": to_checksum_address(self.config.usdg_contract), "value_wei": "0", "data": tx_data,
                    "credits": credits, "created_at": created, "created_block": created_block,
                    "expires_at": expires, "status": "pending"}
        return {"quote_id": quote_id, "chain_id": CHAIN_ID, "payment_method": "native_eth",
                "to": to_checksum_address(self.config.receiver), "value_wei": str(amount),
                "data": tx_data, "credits": credits, "expires_at": expires}

    def verify_purchase(self, wallet: str, quote_id: str, tx_hash: str) -> dict:
        if is_judge_wallet(wallet):
            raise CreditError("Judge Demo sessions cannot purchase testnet credits.", 403)
        self._require_ready()
        if not isinstance(tx_hash, str) or not TX_RE.fullmatch(tx_hash):
            raise CreditError("Enter a valid transaction hash.")
        tx_hash = tx_hash.lower()
        with self._db() as db:
            quote = db.execute("SELECT * FROM quotes WHERE id=? AND wallet=?", (quote_id, wallet)).fetchone()
        if quote is None:
            raise CreditError("Payment quote was not found.", 404)
        # Method is persisted with the quote, never supplied by verification's caller.
        # Native quotes use the ORB1 binding; token quotes require their metadata row.
        method = "native_eth" if quote["tx_data"].startswith(QUOTE_DATA_PREFIX) else "usdg"
        if method not in self.config.methods:
            raise CreditError("This quote's payment method is not enabled.")
        with self._db() as db:
            asset = (db.execute("SELECT * FROM usdg_quotes WHERE quote_id=?", (quote_id,)).fetchone()
                     if method == "usdg" else None)
        if method == "usdg" and (asset is None
                or asset["token_contract"] != self.config.usdg_contract.lower()
                or asset["receiver"] != self.config.receiver.lower()
                or asset["chain_id"] != CHAIN_ID or asset["token_decimals"] != USDG_DECIMALS
                or asset["amount_base_units"] != quote["amount_wei"]):
            raise CreditError("Payment quote does not match this USDG configuration.", 400)
        if quote["tx_hash"]:
            if quote["tx_hash"] == tx_hash:
                return {"status": "credited", "credits": quote["credits"], "balance": self.balance(wallet)}
            raise CreditError("This quote was already paid with another transaction.", 409)
        if asset is not None and time.time() >= quote["expires"]:
            raise CreditError("USDG quote expired. Do not send another payment; contact support if already paid.", 410)
        try:
            if int(self.rpc.call("eth_chainId", []), 16) != CHAIN_ID:
                raise CreditError("RPC is connected to the wrong network.", 503)
            receipt = self.rpc.call("eth_getTransactionReceipt", [tx_hash])
            tx = self.rpc.call("eth_getTransactionByHash", [tx_hash])
            if receipt is None or tx is None:
                raise CreditError("Transaction has not been mined yet.", 409)
            if not isinstance(receipt, dict) or not isinstance(tx, dict):
                raise CreditError("RPC returned incomplete transaction details.", 503)
            block_num = int(receipt["blockNumber"], 16)
            latest = int(self.rpc.call("eth_blockNumber", []), 16)
            if latest - block_num + 1 < self.config.confirmations:
                raise CreditError("Waiting for Arbitrum Sepolia confirmations.", 409)
            block = self.rpc.call("eth_getBlockByNumber", [hex(block_num), False])
            if not isinstance(block, dict) or block.get("hash") != receipt.get("blockHash"):
                raise CreditError("Transaction block is not canonical.", 409)
            if int(block["timestamp"], 16) > quote["expires"]:
                raise CreditError("Payment arrived after this quote expired. Contact support.", 409)
            # A block boundary prevents reuse of an old transfer without relying
            # on precise server/sequencer clock agreement at quote creation.
            if asset is not None and block_num <= asset["created_block"]:
                raise CreditError("USDG payment predates this quote.", 400)
            code = self.rpc.call("eth_getCode", [self.config.receiver, hex(block_num)])
            if code != "0x":
                raise CreditError("Configured receiver must be a wallet, not a contract.", 503)
            target = self.config.usdg_contract if asset is not None else self.config.receiver
            valid = (int(receipt["status"], 16) == 1
                     and receipt.get("transactionHash", "").lower() == tx_hash
                     and tx.get("hash", "").lower() == tx_hash
                     and tx.get("blockHash") == receipt.get("blockHash")
                     and tx.get("from", "").lower() == wallet
                     and receipt.get("from", "").lower() == wallet
                     and tx.get("to", "").lower() == target.lower()
                     and receipt.get("to", "").lower() == target.lower()
                     and wallet != self.config.receiver.lower()
                     and int(tx["value"], 16) == (0 if asset is not None else quote["amount_wei"])
                     and tx.get("input", "").lower() == quote["tx_data"].lower()
                     and (tx.get("chainId") is None or int(tx["chainId"], 16) == CHAIN_ID))
            if asset is not None:
                token_code = self.rpc.call("eth_getCode", [target, hex(block_num)])
                decimals = self.rpc.call("eth_call", [{"to": target, "data": "0x313ce567"}, hex(block_num)])
                valid = (valid and int(tx["chainId"], 16) == CHAIN_ID and token_code not in {None, "0x", "0x0"}
                         and int(decimals, 16) == USDG_DECIMALS
                         and matching_transfer(receipt, wallet, asset["receiver"], asset["amount_base_units"]))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise CreditError("RPC returned incomplete transaction details.", 503) from exc
        if not valid:
            raise CreditError("Transaction does not match this Arbitrum Sepolia quote.", 400)
        with self._db() as db:
            db.begin_write()
            current = db.execute("SELECT * FROM quotes WHERE id=? AND wallet=?" + self._lock(),
                                 (quote_id, wallet)).fetchone()
            if current is not None and current["tx_hash"] == tx_hash:
                # A concurrent verifier already finished this exact purchase.
                db.commit()
                return {"status": "credited", "credits": quote["credits"], "balance": self.balance(wallet)}
            if current is None or current["tx_hash"]:
                raise CreditError("Quote was already credited.", 409)
            if asset is not None and time.time() >= current["expires"]:
                raise CreditError("USDG quote expired before verification completed.", 410)
            inserted = db.execute("INSERT INTO purchases VALUES (?, ?, ?, ?, ?, ?) "
                                  "ON CONFLICT DO NOTHING RETURNING tx_hash",
                                  (tx_hash, quote_id, wallet, quote["credits"], block_num,
                                   int(time.time()))).fetchone()
            if inserted is None:
                raise CreditError("Transaction has already been credited.", 409)
            db.execute("UPDATE quotes SET tx_hash=? WHERE id=?", (tx_hash, quote_id))
            db.execute("INSERT INTO balances(wallet) VALUES (?) ON CONFLICT DO NOTHING", (wallet,))
            db.execute("UPDATE balances SET granted=granted+? WHERE wallet=?", (quote["credits"], wallet))
            db.commit()
        return {"status": "credited", "credits": quote["credits"], "balance": self.balance(wallet)}

    def reserve(self, wallet: str, operation: str, key: str, fingerprint: str, job_id: str) -> tuple[str, bool]:
        if not isinstance(key, str) or not IDEMPOTENCY_RE.fullmatch(key):
            raise CreditError("A valid idempotency key is required.", 400)
        with self._db() as db:
            db.begin_write()
            # Postgres locks one wallet row before reading idempotency state.
            # SQLite's BEGIN IMMEDIATE provides the corresponding write lock.
            if self.database.postgres:
                db.execute("SELECT wallet FROM balances WHERE wallet=? FOR UPDATE", (wallet,)).fetchone()
            prior = db.execute("SELECT * FROM reservations WHERE wallet=? AND idem_key=?", (wallet, key)).fetchone()
            if prior:
                if prior["operation"] != operation or prior["fingerprint"] != fingerprint:
                    raise CreditError("Idempotency key was used for different content.", 409)
                return prior["job_id"], False
            if is_judge_wallet(wallet):
                if self.database.postgres:
                    db.execute("SELECT pg_advisory_xact_lock(749519622)")
                day_prefix = f"{wallet.lower()[:20]}%"
                used_row = db.execute(
                    "SELECT COALESCE(SUM(consumed + reserved), 0) AS used FROM balances WHERE wallet LIKE ?",
                    (day_prefix,),
                ).fetchone()
                if int((used_row["used"] if used_row else 0) or 0) >= self.config.judge_daily_cap:
                    raise CreditError("Daily Judge Demo Mode run limit reached.", 429)
            updated = db.execute("UPDATE balances SET reserved=reserved+1 WHERE wallet=? "
                                 "AND granted-consumed-reserved>=1 RETURNING wallet", (wallet,)).fetchone()
            if updated is None:
                raise CreditError("No testnet credits available. Connect your wallet and buy credits.", 402)
            now = int(time.time())
            db.execute("INSERT INTO reservations VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?)",
                       (job_id, wallet, operation, key, fingerprint, now, now))
            db.commit()
        return job_id, True

    def settle(self, job_id: str, success: bool) -> None:
        with self._db() as db:
            db.begin_write()
            row = db.execute("SELECT wallet, status FROM reservations WHERE job_id=?" + self._lock(),
                             (job_id,)).fetchone()
            if row is None or row["status"] != "reserved":
                return
            db.execute("UPDATE balances SET reserved=reserved-1, consumed=consumed+? WHERE wallet=?",
                       (1 if success else 0, row["wallet"]))
            db.execute("UPDATE reservations SET status=?, updated_at=? WHERE job_id=?",
                       ("consumed" if success else "released", int(time.time()), job_id))
            db.commit()

    def paid_job(self, job_id: str):
        with self._db() as db:
            return db.execute("SELECT wallet, operation, status FROM reservations WHERE job_id=?", (job_id,)).fetchone()

    def save_result(self, job_id: str, payload: dict, run_dir: Path) -> None:
        """Persist the full deliverable result before finalizing a reserved credit."""
        if self.database.postgres:
            with self._db() as db:
                db.execute("INSERT INTO results(job_id, payload, created_at) VALUES (?, ?::jsonb, ?)",
                           (job_id, json.dumps(payload, ensure_ascii=False), int(time.time())))
            return
        destination = run_dir / "orb_result.json"
        temporary = run_dir / f".orb_result.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as result_file:
                json.dump(payload, result_file, ensure_ascii=False)
                result_file.flush()
                os.fsync(result_file.fileno())
            os.replace(temporary, destination)
            if os.name != "nt":
                directory_fd = os.open(run_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def result(self, job_id: str, output_root: Path) -> dict | None:
        if self.database.postgres:
            with self._db() as db:
                row = db.execute("SELECT payload FROM results WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                return None
            payload = row["payload"]
            return json.loads(payload) if isinstance(payload, str) else payload
        try:
            return json.loads((output_root / job_id / "orb_result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None

    def reconcile(self, output_root: Path) -> None:
        # Only a complete, durable result consumes a reserved credit after a
        # restart. Production reads it from Postgres; local mode reads disk.
        with self._db() as db:
            rows = db.execute("SELECT job_id FROM reservations WHERE status='reserved'").fetchall()
        for row in rows:
            result = self.result(row["job_id"], output_root)
            deliverable = (isinstance(result, dict) and result.get("job_id") == row["job_id"]
                           and isinstance(result.get("prompt"), str) and bool(result["prompt"].strip()))
            self.settle(row["job_id"], deliverable)
