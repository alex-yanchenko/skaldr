import base64
import hashlib
import re
from html.parser import HTMLParser


def css_declarations(html: str, selector: str) -> list[str]:
    pattern = r"\s+".join(re.escape(part) for part in selector.split()) + r"\s*\{([^{}]*)\}"
    return [re.sub(r"\s+", "", body) for body in re.findall(pattern, html)]


def strip_rail_rules(name: str) -> dict[str, str]:
    return {
        f".{name}": "grid-template-columns:minmax(9rem,max-content) 1fr; display:grid; gap:0 var(--s3)",
        f".{name} > .tab-list": (
            "flex-direction:column; flex-wrap:nowrap; border-bottom:0; "
            "border-inline-end:1px solid var(--line); margin-inline-end:0; max-height:18rem; "
            "overflow-y:auto; grid-row:1; grid-column:1"
        ),
        f".{name} > .tab-list > *": (
            "border-radius:var(--r-sm); border:0; text-align:start; white-space:normal; overflow:visible; "
            "text-overflow:clip"
        ),
        f".{name} > .tab-pane": "grid-row:1; grid-column:2",
    }


def container_rules(html: str) -> list[tuple[int, dict[str, str]]]:
    return [
        (int(width), dict(re.findall(r"([^{}]+)\{([^{}]*)\}", body)))
        for width, body in re.findall(r"@container \(width < (\d+)px\)\{((?:[^{}]+\{[^{}]*\})*)\}", html)
    ]


def script_hash(body: str) -> str:
    return base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()


class InlineScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.bodies: list[str] = []
        self._collecting = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._collecting = dict(attrs).get("type") != "application/yaml"
            if self._collecting:
                self.bodies.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._collecting = False

    def handle_data(self, data: str) -> None:
        if self._collecting:
            self.bodies[-1] += data


def inline_scripts(html: str) -> list[str]:
    reader = InlineScripts()
    reader.feed(html)
    reader.close()
    return reader.bodies
