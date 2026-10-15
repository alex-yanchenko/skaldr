from typing import Final, Literal, get_args

NotionService = Literal["notion"]
JiraService = Literal["jira"]
Service = Literal[NotionService, JiraService]
SERVICES: Final[tuple[Service, ...]] = get_args(Service)
SERVICE_NAMES: Final[dict[Service, str]] = {"notion": "Notion", "jira": "Jira"}
SERVICES_BY_NAME: Final[dict[str, Service]] = {name: service for service, name in SERVICE_NAMES.items()}
SERVICES_BY_ID: Final[dict[str, Service]] = {service: service for service in SERVICES}
