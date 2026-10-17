"""Stage 4 tests use generated disposable wallets and a mocked chain RPC."""

from __future__ import annotations

import io
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from PIL import Image

from prometheus.api.app import create_app
from prometheus.api.orb_credits import CHAIN_ID, CreditConfig, CreditError, CreditService


TX_HASH = "0x" + "ab" * 32
BLOCK_HASH = "0x" + "cd" * 32


class FakeRpc:
    def __init__(self):
        self.chain = hex(CHAIN_ID)
        self.receipt = None
        self.tx = None
        self.latest = hex(102)
        self.block = {"hash": BLOCK_HASH, "timestamp": hex(int(time.time()))}
        self.code = "0x"
        self.calls = []

    def call(self, method, params):
        self.calls.append(method)
        return {
            "eth_chainId": self.chain,
            "eth_getTransactionReceipt": self.receipt,
            "eth_getTransactionByHash": self.tx,
            "eth_blockNumber": self.latest,
            "eth_getBlockByNumber": self.block,
            "eth_getCode": self.code,
        }[method]

    def paid(self, quote, wallet, receiver, tx_hash=TX_HASH):
        self.tx = {"hash": tx_hash, "from": wallet.address, "to": receiver,
                   "value": hex(int(quote["value_wei"])), "input": quote["data"],
                   "blockHash": BLOCK_HASH, "chainId": hex(CHAIN_ID)}
        self.receipt = {"transactionHash": tx_hash, "status": "0x1", "from": wallet.address,
                        "to": receiver, "blockHash": BLOCK_HASH, "blockNumber": "0x64"}


@pytest.fixture
def setup(tmp_path):
    wallet = Account.create()
    receiver = Account.create().address
    rpc = FakeRpc()
    config = CreditConfig(database=tmp_path / "credits.sqlite3", public_origin="http://localhost",
                          rpc_url="https://rpc.example.invalid", receiver=receiver,
                          enabled=True, price_wei=1000, confirmations=3)
    return CreditService(config, rpc), wallet, receiver, rpc


def sign_in(service, wallet):
    challenge = service.challenge(wallet.address, "http://localhost")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    return challenge, signature, service.sign_in(challenge["nonce"], signature, "http://localhost")


def grant(service, wallet, receiver, rpc, credits=3, tx_hash=TX_HASH):
    quote = service.create_quote(wallet.address.lower(), credits)
    rpc.paid(quote, wallet, receiver, tx_hash)
    return quote, service.verify_purchase(wallet.address.lower(), quote["quote_id"], tx_hash)


def test_wallet_signature_nonce_domain_and_replay(setup):
    service, wallet, _, _ = setup
    with pytest.raises(CreditError, match="origin"):
        service.challenge(wallet.address, "https://evil.example")
    challenge = service.challenge(wallet.address, "http://localhost")
    wrong = Account.create()
    wrong_signature = Account.sign_message(encode_defunct(text=challenge["message"]), wrong.key).signature.hex()
    with pytest.raises(CreditError, match="does not match"):
        service.sign_in(challenge["nonce"], wrong_signature, "http://localhost")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    with pytest.raises(CreditError, match="origin"):
        service.sign_in(challenge["nonce"], signature, "https://evil.example")
    session = service.sign_in(challenge["nonce"], signature, "http://localhost")
    assert service.authenticate("Bearer " + session["token"]) == wallet.address.lower()
    with pytest.raises(CreditError, match="already used"):
        service.sign_in(challenge["nonce"], signature, "http://localhost")
    with sqlite3.connect(service.config.database) as db:
        db.execute("UPDATE sessions SET expires=0")
    with pytest.raises(CreditError, match="expired"):
        service.authenticate("Bearer " + session["token"])


def test_wallet_logout_revokes_only_current_session(setup, tmp_path):
    service, wallet, receiver, rpc = setup
    _, _, first = sign_in(service, wallet)
    _, _, second = sign_in(service, wallet)
    grant(service, wallet, receiver, rpc, credits=1)
    app = create_app(provider="mock", output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads",
                     orb_credit_service=service)
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Origin": "http://localhost", "Authorization": "Bearer " + first["token"]}
        assert client.post("/api/orb/wallet/logout", headers={"Origin": "http://localhost"}).status_code == 401
        assert client.post("/api/orb/wallet/logout", headers={**headers, "Origin": "http://evil.example"}).status_code == 403
        assert client.get("/api/orb/credits/balance", headers=headers).status_code == 200
        assert client.post("/api/orb/wallet/logout", headers=headers).json() == {"status": "signed_out"}
        assert client.post("/api/orb/wallet/logout", headers=headers).status_code == 401
        assert client.get("/api/orb/credits/balance", headers=headers).status_code == 401
        assert client.get("/api/orb/credits/balance", headers={
            "Authorization": "Bearer " + second["token"]}).json()["available"] == 1
    _, _, fresh = sign_in(service, wallet)
    assert service.authenticate("Bearer " + fresh["token"]) == wallet.address.lower()
    assert service.balance(wallet.address.lower())["available"] == 1


def test_expired_session_can_recover_only_its_wallets_saved_job(setup, tmp_path):
    service, wallet, receiver, rpc = setup
    grant(service, wallet, receiver, rpc, credits=1)
    _, _, expired = sign_in(service, wallet)
    job_id = "paid-video-job"
    assert service.reserve(wallet.address.lower(), "decode", "a" * 32, "video-fingerprint", job_id) == (job_id, True)
    output = tmp_path / "output"
    run_dir = output / job_id
    run_dir.mkdir(parents=True)
    service.save_result(job_id, {"job_id": job_id, "prompt": "Recovered video prompt"}, run_dir)
    with sqlite3.connect(service.config.database) as db:
        db.execute("UPDATE sessions SET expires=0")

    app = create_app(provider="mock", output_dir=output, upload_dir=tmp_path / "uploads",
                     orb_credit_service=service)
    _, _, renewed = sign_in(service, wallet)
    other_wallet = Account.create()
    _, _, other = sign_in(service, other_wallet)
    with TestClient(app, base_url="http://localhost") as client:
        path = f"/api/jobs/{job_id}"
        assert client.get(path, headers={"Authorization": "Bearer " + expired["token"]}).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer " + other["token"]}).status_code == 404
        assert client.get(path + "/result", headers={"Authorization": "Bearer " + other["token"]}).status_code == 404
        renewed_headers = {"Authorization": "Bearer " + renewed["token"]}
        assert client.get(path, headers=renewed_headers).json()["state"] == "complete"
        assert client.get(path + "/result", headers=renewed_headers).json()["prompt"] == "Recovered video prompt"
    assert service.balance(wallet.address.lower())["consumed"] == 1
    with sqlite3.connect(service.config.database) as db:
        assert db.execute("SELECT COUNT(*) FROM reservations WHERE job_id=?", (job_id,)).fetchone()[0] == 1


def test_released_paid_job_is_visible_after_same_wallet_reauthentication(setup, tmp_path):
    service, wallet, receiver, rpc = setup
    grant(service, wallet, receiver, rpc, credits=1)
    _, _, expired = sign_in(service, wallet)
    job_id = "failed-video-job"
    service.reserve(wallet.address.lower(), "decode", "b" * 32, "video-fingerprint", job_id)
    service.settle(job_id, False)
    with sqlite3.connect(service.config.database) as db:
        db.execute("UPDATE sessions SET expires=0")
    _, _, renewed = sign_in(service, wallet)
    app = create_app(provider="mock", output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads",
                     orb_credit_service=service)
    with TestClient(app, base_url="http://localhost") as client:
        path = f"/api/jobs/{job_id}"
        assert client.get(path, headers={"Authorization": "Bearer " + expired["token"]}).status_code == 401
        headers = {"Authorization": "Bearer " + renewed["token"]}
        assert client.get(path, headers=headers).json()["state"] == "error"
        assert client.get("/api/orb/credits/balance", headers=headers).json()["available"] == 1
    assert service.balance(wallet.address.lower())["consumed"] == 0


def test_verified_purchase_and_duplicate_grant(setup):
    service, wallet, receiver, rpc = setup
    _, _, session = sign_in(service, wallet)
    quote, verified = grant(service, wallet, receiver, rpc)
    assert verified["balance"]["available"] == 3
    assert service.verify_purchase(wallet.address.lower(), quote["quote_id"], TX_HASH)["balance"]["available"] == 3
    assert CreditService(service.config, rpc).balance(wallet.address.lower())["available"] == 3
    second = service.create_quote(wallet.address.lower(), 1)
    rpc.paid(second, wallet, receiver)
    with pytest.raises(CreditError, match="already been credited"):
        service.verify_purchase(wallet.address.lower(), second["quote_id"], TX_HASH)
    assert service.authenticate("Bearer " + session["token"]) == wallet.address.lower()


@pytest.mark.parametrize("mutate", [
    lambda rpc: setattr(rpc, "chain", "0x1"),
    lambda rpc: rpc.receipt.__setitem__("status", "0x0"),
    lambda rpc: rpc.tx.__setitem__("to", Account.create().address),
    lambda rpc: rpc.tx.__setitem__("from", Account.create().address),
    lambda rpc: rpc.tx.__setitem__("value", "0x1"),
    lambda rpc: rpc.tx.__setitem__("input", "0x"),
    lambda rpc: setattr(rpc, "latest", "0x64"),
    lambda rpc: rpc.block.__setitem__("hash", "0x" + "ee" * 32),
    lambda rpc: setattr(rpc, "code", "0x6000"),
])
def test_rejects_wrong_chain_failed_unrelated_or_unconfirmed_payment(setup, mutate):
    service, wallet, receiver, rpc = setup
    quote = service.create_quote(wallet.address.lower(), 1)
    rpc.paid(quote, wallet, receiver)
    mutate(rpc)
    with pytest.raises(CreditError):
        service.verify_purchase(wallet.address.lower(), quote["quote_id"], TX_HASH)
    assert service.balance(wallet.address.lower())["available"] == 0


def test_transaction_must_exist_and_arrive_before_quote_expiry(setup):
    service, wallet, receiver, rpc = setup
    quote = service.create_quote(wallet.address.lower(), 1)
    with pytest.raises(CreditError, match="not been mined"):
        service.verify_purchase(wallet.address.lower(), quote["quote_id"], TX_HASH)
    rpc.paid(quote, wallet, receiver)
    rpc.block["timestamp"] = hex(quote["expires_at"] + 1)
    with pytest.raises(CreditError, match="after this quote expired"):
        service.verify_purchase(wallet.address.lower(), quote["quote_id"], TX_HASH)


def test_atomic_reservation_idempotency_failure_and_restart(setup, tmp_path):
    service, wallet, receiver, rpc = setup
    grant(service, wallet, receiver, rpc, credits=1)
    address = wallet.address.lower()

    def reserve(index):
        try:
            return service.reserve(address, "enhance", f"key-{index:032d}", "same-fingerprint", f"job-{index}")
        except CreditError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(8)))
    assert len([item for item in outcomes if isinstance(item, tuple)]) == 1
    assert outcomes.count(402) == 7
    winner = next(item[0] for item in outcomes if isinstance(item, tuple))
    assert service.balance(address)["available"] == 0
    service.settle(winner, False)
    assert service.balance(address)["available"] == 1
    same, fresh = service.reserve(address, "enhance", "a" * 32, "content", "second-job")
    assert fresh and same == "second-job"
    assert service.reserve(address, "enhance", "a" * 32, "content", "third-job") == ("second-job", False)
    with pytest.raises(CreditError, match="different content"):
        service.reserve(address, "enhance", "a" * 32, "changed", "fourth-job")
    output = tmp_path / "results"
    (output / "second-job").mkdir(parents=True)
    (output / "second-job" / "orb_result.json").write_text(
        '{"job_id":"second-job","prompt":"done"}', encoding="utf-8")
    restarted = CreditService(service.config, rpc)
    restarted.reconcile(output)
    assert restarted.balance(address) == {"wallet": wallet.address, "available": 0,
                                          "reserved": 0, "consumed": 1, "granted": 1}
    restarted.reconcile(output)
    assert restarted.balance(address)["consumed"] == 1


def test_restart_releases_credit_for_incomplete_result(setup, tmp_path):
    service, wallet, receiver, rpc = setup
    grant(service, wallet, receiver, rpc, credits=1)
    address = wallet.address.lower()
    service.reserve(address, "enhance", "r" * 32, "content", "interrupted-job")
    result_dir = tmp_path / "results" / "interrupted-job"
    result_dir.mkdir(parents=True)
    (result_dir / "orb_result.json").write_text('{"job_id":', encoding="utf-8")

    restarted = CreditService(service.config, rpc)
    restarted.reconcile(tmp_path / "results")
    assert restarted.balance(address)["available"] == 1
    assert restarted.balance(address)["consumed"] == 0


class FakeAI:
    def image(self, operation, source):
        return {"prompt": f"{operation} an actual image", "visual_analysis": {"subject_and_scene": "a test image"},
                "refinements": []}

    def enhance(self, prompt, output, style, detail):
        return f"Enhanced: {prompt}"


def test_paid_api_gate_and_one_credit_per_operation(setup, tmp_path, monkeypatch):
    service, wallet, receiver, rpc = setup
    monkeypatch.setenv("ORB_ENV", "local")
    monkeypatch.setenv("ORB_AI_LOCAL_TESTING", "0")
    monkeypatch.delenv("ORB_ENABLE_NIMIQ_PAYMENTS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    app = create_app(provider="gemini", output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads",
                     orb_ai_service=FakeAI(), orb_credit_service=service)
    with TestClient(app, base_url="http://localhost") as client:
        origin = {"Origin": "http://localhost"}
        assert client.post("/api/orb/enhance", json={"prompt": "A blue car"}, headers=origin).status_code == 401
        challenge = client.post("/api/orb/wallet/challenge", headers=origin,
                                json={"address": wallet.address}).json()
        signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
        signed = client.post("/api/orb/wallet/sign-in", headers=origin,
                             json={"nonce": challenge["nonce"], "signature": signature}).json()
        headers = {**origin, "Authorization": "Bearer " + signed["token"], "X-Orb-Idempotency-Key": "a" * 32}
        assert client.post("/api/orb/enhance", json={"prompt": "A blue car"}, headers=headers).status_code == 402
        grant(service, wallet, receiver, rpc)
        image = Image.new("RGB", (32, 32), "blue")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        for operation in ("decode", "compose"):
            action_headers = {**headers, "X-Orb-Idempotency-Key": operation * 16}
            response = client.post(f"/api/orb/{operation}/file", headers=action_headers,
                                   files={"file": ("reference.png", stream.getvalue(), "image/png")})
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            duplicate = client.post(f"/api/orb/{operation}/file", headers=action_headers,
                                    files={"file": ("reference.png", stream.getvalue(), "image/png")})
            assert duplicate.json()["job_id"] == job_id
            assert client.get(f"/api/jobs/{job_id}").status_code == 401
            for _ in range(100):
                status = client.get(f"/api/jobs/{job_id}", headers=headers).json()
                if status["state"] != "processing":
                    break
                time.sleep(.02)
            assert status["state"] == "complete"
            assert client.get(f"/api/jobs/{job_id}/result", headers=headers).json()["prompt"]
        response = client.post("/api/orb/enhance", headers=headers, json={"prompt": "A blue car"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(100):
            status = client.get(f"/api/jobs/{job_id}", headers=headers).json()
            if status["state"] != "processing":
                break
            time.sleep(.02)
        assert status["state"] == "complete"
        assert service.balance(wallet.address.lower())["consumed"] == 3
        assert service.balance(wallet.address.lower())["available"] == 0
        assert client.post("/api/orb/enhance", headers={**headers, "X-Orb-Idempotency-Key": "b" * 32},
                           json={"prompt": "Another prompt"}).status_code == 402
        assert client.post("/api/analyze", headers=headers).status_code == 402


def test_failed_paid_ai_releases_credit(setup, tmp_path, monkeypatch):
    service, wallet, receiver, rpc = setup
    grant(service, wallet, receiver, rpc, credits=1)
    _, _, session = sign_in(service, wallet)
    monkeypatch.setenv("ORB_ENV", "local")
    monkeypatch.setenv("ORB_AI_LOCAL_TESTING", "0")
    monkeypatch.delenv("ORB_ENABLE_NIMIQ_PAYMENTS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")

    class FailingAI(FakeAI):
        def enhance(self, *args):
            raise RuntimeError("private test failure")

    app = create_app(provider="gemini", output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads",
                     orb_ai_service=FailingAI(), orb_credit_service=service)
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Origin": "http://localhost", "Authorization": "Bearer " + session["token"],
                   "X-Orb-Idempotency-Key": "failure-key-000000000000000000"}
        response = client.post("/api/orb/enhance", json={"prompt": "A blue car"}, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(100):
            status = client.get(f"/api/jobs/{job_id}", headers=headers).json()
            if status["state"] == "error":
                break
            time.sleep(.02)
        assert status["state"] == "error"
        assert "private test failure" not in str(status)
        assert service.balance(wallet.address.lower())["available"] == 1
        assert service.balance(wallet.address.lower())["consumed"] == 0


def test_judge_demo_session_and_rate_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("ORB_ENV", "local")
    monkeypatch.setenv("ORB_AI_LOCAL_TESTING", "0")
    monkeypatch.delenv("ORB_ENABLE_NIMIQ_PAYMENTS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    judge_service = CreditService(CreditConfig(
        database=tmp_path / "judge_credits.sqlite3",
        enabled=False,
        judge_demo_code="opencv-2026-secret",
        judge_daily_cap=12,
        judge_ip_daily_limit=3,
        judge_session_credits=10,
    ))
    app = create_app(provider="gemini", output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads",
                     orb_ai_service=FakeAI(), orb_credit_service=judge_service)
    with TestClient(app, base_url="http://localhost") as client:
        origin = {"Origin": "http://localhost"}
        assert client.get("/api/health").json()["orb_ai_access"] == "credits"
        assert client.post("/api/orb/judge-session", headers=origin, json={"code": "wrong-code"}).status_code == 401
        created = client.post("/api/orb/judge-session", headers=origin, json={"code": "opencv-2026-secret"})
        assert created.status_code == 200
        payload = created.json()
        assert payload["judge_demo"] is True
        assert payload["credits"] == 10
        assert payload["balance"]["available"] == 10
        assert payload["balance"]["judge_demo"] is True
        # Two more sessions from the same IP succeed (3 per day limit), 4th returns 429:
        assert client.post("/api/orb/judge-session", headers=origin, json={"code": "opencv-2026-secret"}).status_code == 200
        assert client.post("/api/orb/judge-session", headers=origin, json={"code": "opencv-2026-secret"}).status_code == 200
        assert client.post("/api/orb/judge-session", headers=origin, json={"code": "opencv-2026-secret"}).status_code == 429

        headers = {**origin, "Authorization": "Bearer " + payload["token"], "X-Orb-Idempotency-Key": "j" * 32}
        # Judge session can run AI operations and settle 1 credit without Web3 RPC:
        response = client.post("/api/orb/enhance", headers=headers, json={"prompt": "A cinematic robot"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(100):
            status = client.get(f"/api/jobs/{job_id}", headers=headers).json()
            if status["state"] != "processing":
                break
            time.sleep(.02)
        assert status["state"] == "complete"
        bal = client.get("/api/orb/credits/balance", headers=headers).json()
        assert bal["available"] == 9
        assert bal["consumed"] == 1
        assert bal["judge_demo"] is True

