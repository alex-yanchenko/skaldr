from collections.abc import Callable, Mapping

import httpx2

from authlib.oauth2.auth import ClientAuth

ClientAuthMethod = Callable[
    [ClientAuth, str, str, dict[str, str], str | bytes], tuple[str, dict[str, str], str | bytes]
]

class OAuth2Client(httpx2.Client):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        token_endpoint_auth_method: str = ...,
        revocation_endpoint_auth_method: str = ...,
        redirect_uri: str | None = ...,
        transport: httpx2.BaseTransport | None = ...,
        timeout: float = ...,
    ) -> None: ...
    def register_client_auth_method(self, auth: tuple[str, ClientAuthMethod]) -> None: ...
    def create_authorization_url(self, url: str, *, state: str, **kwargs: str) -> tuple[str, str]: ...
    def fetch_token(self, url: str, *, authorization_response: str, state: str) -> Mapping[str, object]: ...
    def revoke_token(self, url: str, *, token: str) -> httpx2.Response: ...
