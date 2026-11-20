"""Our offline guard must preserve Python's internal runtime interfaces."""

import socket
import subprocess
import urllib.request

import pytest


pytestmark = pytest.mark.requirement("30.2:offline-test-runtime")
FIXTURE_VERSION = "step30-windows-guard-regression-1"


def test_process_class_remains_subclassable_but_workers_are_blocked():
    class WindowsStylePopen(subprocess.Popen):
        pass

    assert isinstance(subprocess.Popen, type)
    assert issubclass(WindowsStylePopen, subprocess.Popen)
    for constructor in (subprocess.Popen, WindowsStylePopen):
        with pytest.raises(AssertionError, match="external workers"):
            constructor(["not-started"])
    with pytest.raises(AssertionError, match="external workers"):
        subprocess.run(["not-started"])


def test_local_socketpair_can_exchange_runtime_notifications():
    left, right = socket.socketpair()
    try:
        left.settimeout(1)
        right.settimeout(1)
        assert left.send(b"x") == 1
        assert right.recv(1) == b"x"
    finally:
        left.close()
        right.close()


def test_direct_service_connections_remain_blocked_after_socketpair():
    pair = socket.socketpair()
    for connection in pair:
        connection.close()
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="contact services"):
            connection.connect(("127.0.0.1", 11434))
        with pytest.raises(AssertionError, match="contact services"):
            connection.connect_ex(("127.0.0.1", 11434))
    with pytest.raises(AssertionError, match="contact services"):
        socket.create_connection(("127.0.0.1", 11434))
    with pytest.raises(AssertionError, match="contact services"):
        urllib.request.urlopen("http://127.0.0.1:11434/api/version")
