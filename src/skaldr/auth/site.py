from pydantic import HttpUrl, ValidationError

from skaldr.errors import AuthError

JIRA_CLOUD_HOST_SUFFIX = ".atlassian.net"
SITE_REQUIREMENT = "The Jira site must be an https URL like https://<site>.atlassian.net"


def normalise_site(typed: str) -> str:
    origin = https_origin(typed)
    if origin is None:
        raise AuthError(site_refusal(typed))
    return origin


def https_origin(typed: str) -> str | None:
    text = typed.strip()
    if "\\" in text:
        return None
    try:
        url = HttpUrl(text if "://" in text else f"https://{text}")
    except ValidationError:
        return None
    if url.scheme != "https" or not _is_a_jira_cloud_host(url.host):
        return None
    if _carries_userinfo_query_or_fragment(url):
        return None
    return f"https://{url.host}" + ("" if url.port in (None, 443) else f":{url.port}")


def _is_a_jira_cloud_host(host: str | None) -> bool:
    return host is not None and host.endswith(JIRA_CLOUD_HOST_SUFFIX)


def _carries_userinfo_query_or_fragment(url: HttpUrl) -> bool:
    parts = (url.username, url.password, url.query, url.fragment)
    return any(part is not None for part in parts)


def site_refusal(typed: str) -> str:
    if "@" in typed:
        return f"{SITE_REQUIREMENT}, with no user name or password before the host"
    return f"{SITE_REQUIREMENT}, not {typed!r}"
