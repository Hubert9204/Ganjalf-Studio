"""LAN access serves the network on the port the PC already uses."""

from types import SimpleNamespace

from utils import lan_access_settings as lan


def _app(port):
    return SimpleNamespace(state = SimpleNamespace(server_port = port))


def test_network_port_follows_the_server_port(monkeypatch):
    monkeypatch.setattr(lan, "get_lan_access_port", lambda: None)
    ports = tuple(range(8888, 8909))
    assert lan._same_port_first(_app(8888), ports)[0] == 8888
    moved = lan._same_port_first(_app(8890), ports)
    assert moved[0] == 8890 and moved.count(8890) == 1 and 8888 in moved


def test_a_saved_port_or_no_server_port_keeps_the_list(monkeypatch):
    ports = (8888, 8889)
    monkeypatch.setattr(lan, "get_lan_access_port", lambda: 9000)
    assert lan._same_port_first(_app(8890), (9000,)) == (9000,)
    monkeypatch.setattr(lan, "get_lan_access_port", lambda: None)
    assert lan._same_port_first(_app(None), ports) == ports
