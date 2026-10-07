from typing import Final, Literal, get_args

NotionService = Literal["notion"]
JiraService = Literal["jira"]
Service = Literal[NotionService, JiraService]
SERVICES: Final[tuple[Service, ...]] = get_args(Service)
