"""Shared test guards: no test may run the real gcloud or reach the network.

A test that needs either fakes it with monkeypatch. Anything it did not fake
fails here, loudly, instead of reading a real secret or token."""
import subprocess
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def no_real_gcloud_or_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("real subprocess or network call in a test: fake it instead")

    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "check_output", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
