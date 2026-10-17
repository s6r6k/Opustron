from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
ALLOWED_HOSTS = {"inference.local", "api.tokenfactory.nebius.com", "api.tavily.com"}


def _load(name: str) -> dict:
    return yaml.safe_load((DEPLOY / name).read_text())


def _endpoints(policy: dict):
    for key, rule in policy["network_policies"].items():
        for endpoint in rule["endpoints"]:
            yield key, rule, endpoint


@pytest.fixture(params=["openshell-policy.yaml", "presets/chronicle.yaml"])
def policy(request):
    return _load(request.param)


def test_lockdown_policy_shape():
    lockdown = _load("openshell-policy.yaml")
    assert lockdown["version"] == 1
    assert lockdown["process"]["run_as_user"] != "root"
    assert "/" not in lockdown["filesystem_policy"]["read_write"]


def test_lockdown_reaches_only_allowed_hosts():
    hosts = {e["host"] for _, _, e in _endpoints(_load("openshell-policy.yaml"))}
    assert hosts == ALLOWED_HOSTS


def test_every_endpoint_is_enforced_and_scoped(policy):
    for key, rule, endpoint in _endpoints(policy):
        assert not key.startswith("_provider_")
        assert rule["binaries"], key
        # OpenShell defaults to audit (log-only) when enforcement is omitted.
        assert endpoint["enforcement"] == "enforce", key
        assert "*" not in endpoint["host"], key
        assert endpoint["port"] == 443, key
        assert "allowed_ips" not in endpoint, key
        assert endpoint.get("rules"), key
        assert "access" not in endpoint, key


def test_preset_matches_lockdown():
    lockdown = _load("openshell-policy.yaml")["network_policies"]
    preset = _load("presets/chronicle.yaml")
    assert preset["preset"]["name"] == "chronicle"
    for key, rule in preset["network_policies"].items():
        assert rule == lockdown[key], key
