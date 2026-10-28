from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, field_validator, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.models.primitives import (
    REFERENCE_KEY_PATTERN,
    BadgeColor,
    Icon,
    NotionWidth,
    RichText,
    require_web_url,
    url_defect,
)


class Badge(FrozenModel):
    label: str = Field(description="Chip text for this tag/status.")
    tone: BadgeColor = Field(
        description="Chip colour: a palette name (slate/blue/…) or its semantic tone twin (neutral/info/…)."
    )
    legend: str | Literal[False] = Field(
        description="One-line meaning, shown in the derived legend. Set `false` to keep this badge out "
        "of the legend entirely, for a one-off inline chip that needs no explanation.",
    )


PERSON_KEY_PATTERN = REFERENCE_KEY_PATTERN
NOTION_USER_PATTERN = r"^user://[0-9A-Fa-f-]+$"
SLACK_MEMBER_PATTERN = r"^U[0-9A-Z]+$"
JIRA_SITE_SCHEME = "https://"


PersonKey = Annotated[str, StringConstraints(pattern=rf"^{PERSON_KEY_PATTERN}$")]


class Person(FrozenModel):
    notion: str | None = Field(
        default=None,
        pattern=NOTION_USER_PATTERN,
        description="The person's Notion user id as a `user://` URI. The Notion Markdown export writes a "
        "`[Ada](user:ada)` link as a mention of this user; without it the link is its label.",
    )
    jira: str | None = Field(
        default=None,
        description="The person's Jira account id, for the Jira writer. Not read when rendering.",
    )
    slack: str | None = Field(
        default=None,
        pattern=SLACK_MEMBER_PATTERN,
        description="The person's Slack member id, such as U0EXAMPLE1. The Slack canvas export writes a "
        "`[Ada](user:ada)` link as a mention of this member; without it the link is its label.",
    )


class Meta(FrozenModel):
    title: str = Field(description="Page title (h1).")
    subtitle: list[str] = Field(default_factory=list, description="Subtitle lines under the title.")
    source: RichText | None = Field(
        default=None, description="Provenance, in rich text (`code` spans, links); feeds the footer."
    )
    notion_width: NotionWidth = Field(
        default="normal",
        description="The Notion page width the Notion export sizes tables for: `normal` (default) leaves a "
        "table without author widths to Notion; `full` gives every table column widths that add up to "
        "1,200 px, for a page switched to Full width.",
    )
    date: str | None = Field(default=None, description="Report date; feeds the footer (never auto-now).")
    updated: str | None = Field(
        default=None,
        description="When the report was last revised; feeds the footer as 'updated <value>'. A "
        "free-form label like the date (author it; never auto-now).",
    )
    toc: bool = Field(
        default=False, description="Render a table of contents from top-level level-2 headings and sections."
    )
    hero: bool = Field(
        default=False,
        description="Opt-in hero header: a larger display title + subtitle in a tinted band, for a page "
        "that opens by selling an idea rather than a plain report header.",
    )
    numbered: bool = Field(
        default=False,
        description="Opt-in numbered sections: each top-level level-2 heading on the HTML page gets a large "
        "number (01, 02, …), in the left margin on a wide screen and above the title on a narrow one. The "
        "exports ignore it.",
    )
    people: dict[PersonKey, Person] = Field(
        default_factory=dict[str, Person],
        description="The people a `[Ada](user:ada)` link can name, by key. A `user:` link to a key not "
        "listed here fails the build.",
    )
    jira_site: str | None = Field(
        default=None,
        description="The https:// address of your Jira site, such as https://example.atlassian.net. A "
        "`[ABC-123](jira:ABC-123)` link points at `<jira_site>/browse/ABC-123`; without it the issue key "
        "is shown as text.",
    )

    @field_validator("jira_site")
    @classmethod
    def _jira_site_is_an_https_address(cls, site: str | None) -> str | None:
        if site is None:
            return None
        if not site.startswith(JIRA_SITE_SCHEME):
            raise ValueError(f"jira_site must be an {JIRA_SITE_SCHEME} URL")
        address = urlsplit(site)
        if not address.hostname:
            raise ValueError(f"jira_site {site!r} names no host: write it as https://<your-site>")
        if address.username is not None or address.password is not None:
            raise ValueError(f"jira_site {site!r} must not hold a username or password")
        if "?" in site:
            raise ValueError(f"jira_site {site!r} must not hold a query")
        if "#" in site:
            raise ValueError(f"jira_site {site!r} must not hold a fragment")
        defect = url_defect(site)
        if defect is not None:
            raise ValueError(f"jira_site {site!r} is not a valid URL ({defect})")
        return site.rstrip("/")

    icon: Icon | None = Field(
        default=None,
        description="One emoji shown beside the title and used as the page's favicon; the Notion page icon.",
    )
    cover: str | None = Field(
        default=None,
        description="An http:// or https:// image address for the page cover. The HTML page allows no remote "
        "images, so it shows a 'Cover image' link under the title instead; the Notion page cover.",
    )

    @model_validator(mode="after")
    def _cover_is_a_web_url(self) -> "Meta":
        if self.cover is not None:
            require_web_url(self.cover, "'cover'")
        return self
