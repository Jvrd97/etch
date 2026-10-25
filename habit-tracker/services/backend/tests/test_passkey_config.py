"""
Настройки passkey: когда он включён и какие сочетания не стартуют.

WebAuthn не работает на IP-адресе и на origin, чьё имя не лежит под RP ID, —
браузер просто откажет, и человек увидит неработающую кнопку без объяснений.
Поэтому такие сочетания отбиваются при сборке настроек, с сообщением,
называющим переменную.
"""

# [review:need-review] 205
# summary: WEBAUTHN_RP_ID / WEBAUTHN_ORIGINS — off when empty, comma-separated origins, a *.ts.net name accepted, an IP RP ID, a half-filled pair and an origin outside the RP ID refused at build
import pytest
from pydantic import ValidationError

from app.core.config import Settings

TS_NET_NAME = "habit.tail1234.ts.net"


def build(**values: object) -> Settings:
    return Settings(**values)  # type: ignore[arg-type]  # BaseSettings takes **kwargs


def test_passkey_is_off_by_default() -> None:
    assert build().passkey_enabled is False


def test_ts_net_name_turns_passkey_on() -> None:
    config = build(
        WEBAUTHN_RP_ID=TS_NET_NAME, WEBAUTHN_ORIGINS=[f"https://{TS_NET_NAME}"]
    )
    assert config.passkey_enabled is True
    assert config.WEBAUTHN_RP_NAME == "Habit Tracker"


def test_localhost_with_a_port_is_a_valid_origin() -> None:
    config = build(
        WEBAUTHN_RP_ID="localhost", WEBAUTHN_ORIGINS=["http://localhost:3805"]
    )
    assert config.passkey_enabled is True


def test_origins_are_read_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBAUTHN_RP_ID", TS_NET_NAME)
    monkeypatch.setenv(
        "WEBAUTHN_ORIGINS", f"https://{TS_NET_NAME}, https://app.{TS_NET_NAME}"
    )
    assert Settings().WEBAUTHN_ORIGINS == [
        f"https://{TS_NET_NAME}",
        f"https://app.{TS_NET_NAME}",
    ]


@pytest.mark.parametrize(
    ("values", "names"),
    [
        ({"WEBAUTHN_RP_ID": TS_NET_NAME}, "WEBAUTHN_ORIGINS"),
        ({"WEBAUTHN_ORIGINS": [f"https://{TS_NET_NAME}"]}, "WEBAUTHN_RP_ID"),
        (
            {
                "WEBAUTHN_RP_ID": "100.121.220.42",
                "WEBAUTHN_ORIGINS": ["http://100.121.220.42:3000"],
            },
            "IP address",
        ),
        (
            {
                "WEBAUTHN_RP_ID": TS_NET_NAME,
                "WEBAUTHN_ORIGINS": ["https://evil.example"],
            },
            "evil.example",
        ),
        (
            {
                "WEBAUTHN_RP_ID": TS_NET_NAME,
                "WEBAUTHN_ORIGINS": [f"https://not{TS_NET_NAME}"],
            },
            f"not{TS_NET_NAME}",
        ),
    ],
    ids=["no-origins", "no-rp-id", "ip-rp-id", "foreign-origin", "suffix-lookalike"],
)
def test_incoherent_passkey_config_refuses_to_build(
    values: dict[str, object], names: str
) -> None:
    with pytest.raises(ValidationError, match=names):
        build(**values)
