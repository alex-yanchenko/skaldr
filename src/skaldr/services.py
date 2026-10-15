from typing import Final, Literal, get_args

NotionService = Literal["notion"]
JiraService = Literal["jira"]
SlackService = Literal["slack"]
Service = Literal[NotionService, JiraService, SlackService]
SERVICES: Final[tuple[Service, ...]] = get_args(Service)
SERVICE_NAMES: Final[dict[Service, str]] = {"notion": "Notion", "jira": "Jira", "slack": "Slack"}
SERVICES_BY_NAME: Final[dict[str, Service]] = {name: service for service, name in SERVICE_NAMES.items()}


def service_with_id(text: str) -> Service | None:
    return next((service for service in SERVICES if service == text), None)
