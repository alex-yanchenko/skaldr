class ClientAuth:
    client_id: str
    client_secret: str

def encode_client_secret_basic(
    client: ClientAuth, method: str, uri: str, headers: dict[str, str], body: str | bytes
) -> tuple[str, dict[str, str], str | bytes]: ...
