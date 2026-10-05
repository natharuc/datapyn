"""Exercise the installed SDK against request fixtures verified with OAuthLib 3.3.1.

OAuthLib 4 fixes a provider-side PKCE comparison. Its breaking changes affect
revocation/provider endpoints; Databricks uses the retained client APIs:
https://github.com/oauthlib/oauthlib/security/advisories/GHSA-xpv3-w29h-x7cv
https://github.com/oauthlib/oauthlib/blob/v4.0.0/CHANGELOG.rst
The transport, browser and callback server are replaced; no authentication,
network access, browser window or listening socket is used by these tests.
"""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from databricks.sql.auth import oauth as sdk
from databricks.sql.auth.auth_utils import decode_token
from databricks.sql.auth.endpoint import AzureOAuthEndpointCollection, InHouseOAuthEndpointCollection
from databricks.sql.common.http import HttpMethod
from oauthlib.oauth2 import MismatchingStateError, WebApplicationClient


SIGNING_SECRET = "test-only-signing-secret-that-is-long-enough"
TOKEN_URL = "https://example.invalid/token"
CLIENT_ID = "test-client"
VERIFIER = "v" * 43
# Captured from the SDK with OAuthLib 3.3.1, using the deterministic verifier.
CHALLENGE = "7w_YNF9DSfIdPf_pRjSq646_kPr-2-o9NAl16JGghdM"


@pytest.fixture
def tokens():
    return SimpleNamespace(
        access=jwt.encode({"exp": 4294967295, "sub": "test-user"}, SIGNING_SECRET, algorithm="HS256"),
        expired=jwt.encode({"exp": 1, "sub": "test-user"}, SIGNING_SECRET, algorithm="HS256"),
    )


@pytest.fixture
def transport(tokens):
    class Transport:
        def __init__(self):
            self.requests = []

        def request(self, method, url, body=None, headers=None):
            self.requests.append(
                {
                    "method": method.value,
                    "url": url,
                    "headers": headers or {},
                    "form": parse_qs(body) if body else {},
                }
            )
            document = (
                {"token_endpoint": TOKEN_URL}
                if method == HttpMethod.GET
                else {
                    "access_token": tokens.access,
                    "refresh_token": "next-refresh",
                    "token_type": "Bearer",
                }
            )
            return SimpleNamespace(status=200, data=json.dumps(document).encode())

    return Transport()


@pytest.fixture
def callback(monkeypatch):
    captured = SimpleNamespace(authorizations=[], wrong_state=False)

    class Handler:
        def __init__(self, name):
            self.request_path = None

    class Server:
        def __init__(self, address, handler):
            self.handler = handler

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def handle_request(self):
            state = "invalid-state" if captured.wrong_state else captured.authorizations[-1]["query"]["state"][0]
            self.handler.request_path = "?code=test-code&state=" + state

    def open_browser(uri):
        parsed = urlparse(uri)
        captured.authorizations.append({"url": parsed._replace(query="").geturl(), "query": parse_qs(parsed.query)})
        return True

    monkeypatch.setattr(sdk, "HTTPServer", Server)
    monkeypatch.setattr(sdk, "OAuthHttpSingleRequestHandler", Handler)
    monkeypatch.setattr(sdk.webbrowser, "open_new", open_browser)
    monkeypatch.setattr(
        sdk.OAuthManager, "_OAuthManager__token_urlsafe", staticmethod(lambda n=32: "state" if n == 16 else VERIFIER)
    )
    return captured


@pytest.mark.parametrize(
    "endpoint,host,metadata_url",
    [
        (
            InHouseOAuthEndpointCollection,
            "demo.cloud.databricks.com",
            "https://demo.cloud.databricks.com/oidc/.well-known/oauth-authorization-server",
        ),
        (
            AzureOAuthEndpointCollection,
            "demo.azuredatabricks.net",
            "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration",
        ),
    ],
)
def test_actual_sdk_authorization_callback_pkce_and_token_exchange(
    endpoint, host, metadata_url, transport, callback, tokens
):
    manager = sdk.OAuthManager([8020], CLIENT_ID, endpoint(), transport)
    assert manager.get_tokens(host, ["sql", "offline_access"]) == (tokens.access, "next-refresh")
    assert callback.authorizations == [
        {
            "url": f"https://{host}/oidc/oauth2/v2.0/authorize",
            "query": {
                "response_type": ["code"],
                "client_id": [CLIENT_ID],
                "redirect_uri": ["http://localhost:8020"],
                "scope": ["sql offline_access"],
                "state": ["state"],
                "code_challenge": [CHALLENGE],
                "code_challenge_method": ["S256"],
            },
        }
    ]
    assert transport.requests == [
        {"method": "GET", "url": metadata_url, "headers": {}, "form": {}},
        {
            "method": "POST",
            "url": TOKEN_URL,
            "headers": {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            "form": {
                "grant_type": ["authorization_code"],
                "client_id": [CLIENT_ID],
                "code": ["test-code"],
                "redirect_uri": ["http://localhost:8020"],
                "code_verifier": [VERIFIER],
            },
        },
    ]


def test_actual_sdk_rejects_callback_state_mismatch_before_token_exchange(transport, callback):
    callback.wrong_state = True
    manager = sdk.OAuthManager([8020], CLIENT_ID, InHouseOAuthEndpointCollection(), transport)
    with pytest.raises(MismatchingStateError):
        manager.get_tokens("demo.cloud.databricks.com", ["sql"])
    assert [request["method"] for request in transport.requests] == ["GET"]


def test_actual_sdk_refreshes_expired_token_and_reuses_valid_token(transport, tokens):
    manager = sdk.OAuthManager([8020], CLIENT_ID, InHouseOAuthEndpointCollection(), transport)
    assert manager.check_and_refresh_access_token("demo.cloud.databricks.com", tokens.expired, "old-refresh") == (
        tokens.access,
        "next-refresh",
        True,
    )
    assert transport.requests[-1] == {
        "method": "POST",
        "url": TOKEN_URL,
        "headers": {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        "form": {"grant_type": ["refresh_token"], "client_id": [CLIENT_ID], "refresh_token": ["old-refresh"]},
    }
    count = len(transport.requests)
    assert manager.check_and_refresh_access_token("demo.cloud.databricks.com", tokens.access, "next-refresh") == (
        tokens.access,
        "next-refresh",
        False,
    )
    assert len(transport.requests) == count
    with pytest.raises(RuntimeError, match="expired"):
        manager.check_and_refresh_access_token("demo.cloud.databricks.com", tokens.expired, "")
    assert len(transport.requests) == count


def test_actual_sdk_client_credentials_exchange_preserves_cached_token(transport, tokens):
    source = sdk.ClientCredentialsTokenSource(TOKEN_URL, CLIENT_ID, "fake-test-secret", transport, {"scope": "sql"})
    token = source.get_token()
    assert token.access_token == tokens.access
    assert token.refresh_token == "next-refresh"
    assert token.token_type == "Bearer"
    assert transport.requests == [
        {
            "method": "POST",
            "url": TOKEN_URL,
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "form": {
                "grant_type": ["client_credentials"],
                "client_id": [CLIENT_ID],
                "client_secret": ["fake-test-secret"],
                "scope": ["sql"],
            },
        }
    ]
    assert source.get_token() is token
    assert len(transport.requests) == 1


def test_installed_oauth_client_parses_tokens_and_sdk_reads_jwt_claims(tokens):
    client = WebApplicationClient(CLIENT_ID, scope=["sql"])
    parsed = client.parse_request_body_response(
        json.dumps(
            {
                "access_token": tokens.access,
                "token_type": "Bearer",
                "scope": "sql",
                "expires_in": 3600,
            }
        )
    )
    assert parsed["access_token"] == tokens.access
    assert parsed["expires_in"] == 3600
    assert parsed["scope"] == ["sql"]
    assert decode_token(tokens.access) == {"exp": 4294967295, "sub": "test-user"}


@pytest.mark.parametrize("decode", [jwt.decode, jwt.decode_complete])
def test_jwt_options_reuse_cannot_disable_expiration_validation(decode, tokens):
    options = {"verify_signature": False}
    decode(tokens.expired, options=options)
    assert options == {"verify_signature": False}
    options["verify_signature"] = True
    with pytest.raises(jwt.ExpiredSignatureError):
        decode(tokens.expired, SIGNING_SECRET, algorithms=["HS256"], options=options)
