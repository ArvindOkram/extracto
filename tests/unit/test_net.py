import pytest

from extracto.domain.net import is_public_ip


@pytest.mark.parametrize(
    "ip",
    ["93.184.216.34", "8.8.8.8", "142.250.183.14", "2607:f8b0:4004:c07::64"],
)
def test_public(ip: str) -> None:
    assert is_public_ip(ip)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.1.2.3",  # private
        "172.16.0.1",
        "192.168.1.10",
        "169.254.169.254",  # link-local / cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",
    ],
)
def test_not_public(ip: str) -> None:
    assert not is_public_ip(ip)


def test_garbage_is_not_public() -> None:
    assert not is_public_ip("not-an-ip")
