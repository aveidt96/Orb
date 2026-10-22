"""CreditService integration with simulated separate containers and mocked S3/RPC."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from prometheus.api.orb_s3_ledger import S3LedgerDatabase, LedgerConflict, LedgerUnavailable, LEDGER_KEY
from prometheus.api.orb_credits import CreditService, CreditConfig, CreditError
from tests.s3_ledger_support import FakeLedgerS3
from tests.test_orb_credits import FakeRpc, grant


@pytest.fixture
def containers(tmp_path, monkeypatch):
    s3 = FakeLedgerS3()
    ledger = S3LedgerDatabase("test-ledger", s3)
    assert ledger.bootstrap()
    monkeypatch.setenv("ORB_SERVERLESS_SYNC", "1")
    monkeypatch.setenv("ORB_AWS_S3_BUCKET", "test-ledger")
    monkeypatch.setattr("prometheus.api.orb_credits.S3LedgerDatabase",
                        lambda bucket, **kwargs: S3LedgerDatabase(bucket, s3, **kwargs))
    wallet, receiver, rpc = Account.create(), Account.create().address, FakeRpc()
    def container(name):
        return CreditService(CreditConfig(database=tmp_path / name, public_origin="http://localhost",
            rpc_url="https://rpc.example.invalid", receiver=receiver, enabled=True,
            session_secret="test-shared-secret", judge_demo_code="test-judge", price_wei=1000), rpc)
    return container, wallet, receiver, rpc, s3


def test_cross_container_quotes_grants_balances_and_replays(containers):
    container, wallet, receiver, rpc, s3 = containers
    a, b, c = container("a"), container("b"), container("c")
    challenge = a.challenge(wallet.address, "http://localhost")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    token = b.sign_in(challenge["nonce"], signature, "http://localhost")["token"]
    with pytest.raises(CreditError, match="already used"):
        c.sign_in(challenge["nonce"], signature, "http://localhost")
    quote = a.create_quote(wallet.address.lower(), 3)
    rpc.paid(quote, wallet, receiver)
    result = b.verify_purchase(wallet.address.lower(), quote["quote_id"], "0x" + "ab" * 32)
    assert result["balance"]["available"] == 3
    assert c.balance(c.authenticate("Bearer " + token))["available"] == 3
    b.verify_purchase(wallet.address.lower(), quote["quote_id"], "0x" + "ab" * 32)
    assert c.balance(wallet.address.lower())["granted"] == 3
    another_quote = c.create_quote(wallet.address.lower(), 3)
    with pytest.raises(CreditError):
        c.verify_purchase(wallet.address.lower(), another_quote["quote_id"], "0x" + "ab" * 32)
    assert a.balance(wallet.address.lower())["granted"] == 3
    assert not a.config.database.exists()


def test_reservations_settlement_result_and_logout_survive_containers(containers, tmp_path):
    container, wallet, receiver, rpc, _ = containers
    a, b = container("a"), container("b")
    challenge = a.challenge(wallet.address, "http://localhost")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    token = a.sign_in(challenge["nonce"], signature, "http://localhost")["token"]
    grant(a, wallet, receiver, rpc)
    key = "idempotent-key-0001"
    assert a.reserve(wallet.address.lower(), "decode", key, "fingerprint", "job1") == ("job1", True)
    assert b.reserve(wallet.address.lower(), "decode", key, "fingerprint", "job2") == ("job1", False)
    b.reconcile(tmp_path)  # cold starts cannot release another live invocation
    assert a.balance(wallet.address.lower())["reserved"] == 1
    payload = {"job_id": "job1", "prompt": "Test result"}
    a.save_result("job1", payload, tmp_path)
    assert b.result("job1", tmp_path) == payload
    b.settle("job1", True)
    a.settle("job1", True)
    a.reserve(wallet.address.lower(), "enhance", "idempotent-key-0002", "fingerprint", "job3")
    b.settle("job3", False)
    assert b.balance(wallet.address.lower()) == {"wallet": wallet.address, "granted": 3,
                                                "consumed": 1, "reserved": 0, "available": 2}
    a.logout("Bearer " + token)
    with pytest.raises(CreditError, match="expired"):
        b.authenticate("Bearer " + token)


def test_concurrent_reservations_do_not_overspend(containers):
    container, wallet, receiver, rpc, _ = containers
    a = container("a")
    grant(a, wallet, receiver, rpc, credits=1)
    def reserve(index):
        try:
            return container(str(index)).reserve(wallet.address.lower(), "decode", f"key-concurrent-{index:04}", "fp", f"job{index}")[1]
        except CreditError as exc:
            assert exc.status in {402, 409}
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1
    assert a.balance(wallet.address.lower())["reserved"] == 1


def test_concurrent_verification_grants_once(containers):
    container, wallet, receiver, rpc, _ = containers
    quote = container("a").create_quote(wallet.address.lower(), 3)
    rpc.paid(quote, wallet, receiver)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda i: container(str(i)).verify_purchase(wallet.address.lower(),
                    quote["quote_id"], "0x" + "ab" * 32), range(4)))
    assert len(outcomes) == 4
    assert container("final").balance(wallet.address.lower())["granted"] == 3


def test_conflict_retry_and_s3_failure_fail_closed(containers):
    container, wallet, receiver, rpc, s3 = containers
    a = container("a")
    s3.conflict_once = True
    grant(a, wallet, receiver, rpc)
    assert a.balance(wallet.address.lower())["available"] == 3
    s3.fail = True
    with pytest.raises(CreditError) as exc:
        a.reserve(wallet.address.lower(), "decode", "key-unavailable-0001", "fp", "job1")
    assert exc.value.status == 503
    s3.fail = False
    assert a.balance(wallet.address.lower())["reserved"] == 0


def test_stale_snapshot_cannot_overwrite_and_bootstrap_is_idempotent():
    s3 = FakeLedgerS3()
    a, b = S3LedgerDatabase("test", s3), S3LedgerDatabase("test", s3)
    with pytest.raises(LedgerUnavailable, match="not initialized"):
        with a.session(): pass
    assert a.bootstrap()
    before = s3.objects.copy()
    assert not b.bootstrap()
    assert s3.objects == before
    with a.session() as first:
        first.execute("INSERT INTO balances(wallet) VALUES ('a')")
        with b.session() as second:
            second.execute("INSERT INTO balances(wallet) VALUES ('b')")
        with pytest.raises(LedgerConflict):
            first.commit()
        first.saved_changes = first.connection.total_changes  # discard test snapshot
    with b.session() as final:
        assert [r["wallet"] for r in final.execute("SELECT wallet FROM balances").fetchall()] == ["b"]


def test_judge_grants_are_shared_and_never_replenished_on_auth(containers):
    container, _, _, _, _ = containers
    a, b = container("a"), container("b")
    session = a.create_judge_session("test-judge", "127.0.0.1")
    wallet = b.authenticate("Bearer " + session["token"])
    a.reserve(wallet, "decode", "judge-idempotency-001", "fp", "job1")
    a.settle("job1", True)
    assert b.balance(b.authenticate("Bearer " + session["token"]))["available"] == 9


def test_corrupt_or_unsupported_ledger_never_resets():
    s3 = FakeLedgerS3()
    db = S3LedgerDatabase("test", s3)
    s3.objects["test", LEDGER_KEY] = (b"broken", '"old"')
    with pytest.raises(LedgerUnavailable, match="Invalid"):
        db.bootstrap()
    assert s3.puts == 0


def test_usdg_quote_and_transfer_survive_different_containers(containers):
    from dataclasses import replace
    from tests.test_orb_usdg import UsdgRpc
    container, wallet, _, _, _ = containers
    config = replace(container("base").config, payment_methods=("native_eth", "usdg"))
    rpc = UsdgRpc()
    a, b = CreditService(config, rpc), CreditService(config, rpc)
    quote = a.create_quote(wallet.address.lower(), 3, "usdg")
    assert quote["amount_base_units"] == "9000"
    assert quote["value_wei"] == "0"
    rpc.paid_usdg(quote, wallet)
    b.verify_purchase(wallet.address.lower(), quote["quote_id"], "0x" + "ab" * 32)
    assert a.balance(wallet.address.lower())["available"] == 3
    a.verify_purchase(wallet.address.lower(), quote["quote_id"], "0x" + "ab" * 32)
    assert b.balance(wallet.address.lower())["granted"] == 3


def test_existing_lambda_environment_is_preserved(monkeypatch):
    from deploy.deploy_aws_lambda import lambda_env_vars
    monkeypatch.setenv("ORB_CREDIT_PRICE_WEI", "999")
    existing = {"ORB_PAYMENT_METHODS": "native_eth,usdg", "ORB_CREDIT_PRICE_WEI": "123",
                "ORB_CREDIT_RECEIVER": "receiver-placeholder", "ORB_SESSION_SECRET": "test-secret",
                "GEMINI_API_KEY": "test-key-not-real", "ORB_AI_MODEL": "existing-model",
                "ORB_CUSTOM_SETTING": "keep-me", "ORB_DATABASE_URL": "private-placeholder"}
    variables = lambda_env_vars("test-bucket", existing)
    for key, value in existing.items():
        assert variables[key] == value


def test_http_result_recovery_on_another_container_consumes_once(containers, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from prometheus.api.app import create_app
    container, wallet, receiver, rpc, _ = containers
    a, b = container("a"), container("b")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    challenge = a.challenge(wallet.address, "http://localhost")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), wallet.key).signature.hex()
    token = a.sign_in(challenge["nonce"], signature, "http://localhost")["token"]
    grant(a, wallet, receiver, rpc)
    job = "a" * 32
    a.reserve(wallet.address.lower(), "decode", "http-recovery-key-001", "fp", job)
    payload = {"job_id": job, "operation": "decode", "prompt": "Durable result"}
    a.save_result(job, payload, tmp_path)
    app = create_app(provider="gemini", orb_credit_service=b,
                     output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads")
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Authorization": "Bearer " + token, "Origin": "http://localhost"}
        assert client.get("/api/orb/credits/config").json()["ledger_storage"] == "s3"
        assert client.get(f"/api/jobs/{job}", headers=headers).json()["state"] == "complete"
        assert client.get(f"/api/jobs/{job}/result", headers=headers).json() == payload
        assert client.get(f"/api/jobs/{job}/result", headers=headers).json() == payload
        assert client.get(f"/api/jobs/{job}/result").status_code == 401
        assert client.get("/api/orb/credits/balance", headers=headers).json()["consumed"] == 1
        assert client.post("/api/orb/wallet/logout", headers=headers).status_code == 200
        assert client.get("/api/orb/credits/balance", headers=headers).status_code == 401
