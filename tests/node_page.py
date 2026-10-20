import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TypedDict

import pytest

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="the page scripts run under node")

_PAGE_DRIVER = """
const vm = require("vm");
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const storage = Object.assign({}, input.storage);

function denied() { throw new Error("storage denied"); }
const localStorage = {
  getItem(key) { if (input.storage_throws) denied(); return key in storage ? storage[key] : null; },
  setItem(key, value) { if (input.storage_throws) denied(); storage[key] = String(value); },
  removeItem(key) { if (input.storage_throws) denied(); delete storage[key]; },
};

function makeElement(dataset) {
  return {
    dataset: dataset, attributes: {}, listeners: {}, hidden: false, classes: new Set(),
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; },
    removeAttribute(name) { delete this.attributes[name]; },
    addEventListener(type, listener) { (this.listeners[type] = this.listeners[type] || []).push(listener); },
    classList: { toggle(name, on) { return on; } },
    contains() { return false; },
  };
}

const root = makeElement({});
const button = makeElement({});
const menu = makeElement({});
const controls = makeElement({ open: "false" });
const items = input.controls.map(function (pair) { return makeElement({ set: pair[0], val: pair[1] }); });
controls.querySelector = function (selector) {
  return { ".sc-btn": button, ".sc-menu": menu }[selector] || null;
};
controls.querySelectorAll = function (selector) {
  const named = selector.match(/data-set="(\\w+)"/);
  return named ? items.filter(function (item) { return item.dataset.set === named[1]; }) : items;
};
const disclosures = (input.disclosures || []).map(function (open) {
  const element = makeElement({});
  element.open = open;
  return element;
});
const document = {
  documentElement: root,
  querySelector(selector) { return selector === ".sc" ? controls : null; },
  querySelectorAll(selector) { return selector === "details" ? disclosures : []; },
  addEventListener() {},
};
const windowListeners = {};
const window = {
  addEventListener(type, listener) { (windowListeners[type] = windowListeners[type] || []).push(listener); },
};
const context = vm.createContext({ document: document, window: window, localStorage: localStorage });

input.scripts.forEach(function (script) { vm.runInContext(script, context); });
input.clicks.forEach(function (pair) {
  const item = items.find(function (candidate) {
    return candidate.dataset.set === pair[0] && candidate.dataset.val === pair[1];
  });
  item.listeners.click.forEach(function (listener) { listener({ stopPropagation() {} }); });
});

function openStates() { return disclosures.map(function (element) { return element.open; }); }
function fire(type) { (windowListeners[type] || []).forEach(function (listener) { listener({}); }); }
fire("beforeprint");
const duringPrint = openStates();
fire("afterprint");
process.stdout.write(JSON.stringify({
  attributes: root.attributes, storage: storage, printed: { during: duringPrint, after: openStates() },
}));
"""

_FUNCTION_DRIVER = """
const vm = require("vm");
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const context = vm.createContext({});
vm.runInContext(input.source, context);
const call = input.call + "(" + JSON.stringify(input.argument) + ")";
process.stdout.write(JSON.stringify(vm.runInContext(call, context)));
"""

CONTROL_ITEMS = (
    ("theme", "auto"),
    ("theme", "light"),
    ("theme", "dark"),
    ("width", "default"),
    ("width", "wide"),
    ("width", "full"),
)


@dataclass(frozen=True)
class PageOutcome:
    attributes: dict[str, str]
    storage: dict[str, str]


@dataclass(frozen=True)
class PageRun:
    storage: dict[str, str] = field(default_factory=dict[str, str])
    storage_throws: bool = False
    clicks: tuple[tuple[str, str], ...] = ()


def inline_scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)


def script_containing(html: str, marker: str) -> str:
    return next(script for script in inline_scripts(html) if marker in script)


@dataclass(frozen=True)
class PrintCycle:
    during: tuple[bool, ...]
    after: tuple[bool, ...]


class _PrintedStates(TypedDict):
    during: list[bool]
    after: list[bool]


class _DrivenPage(TypedDict):
    attributes: dict[str, str]
    storage: dict[str, str]
    printed: _PrintedStates


def _drive_page(scripts: list[str], run: PageRun, disclosures: list[bool]) -> _DrivenPage:
    assert NODE is not None
    payload = {
        "scripts": scripts,
        "storage": run.storage,
        "storage_throws": run.storage_throws,
        "controls": CONTROL_ITEMS,
        "clicks": run.clicks,
        "disclosures": disclosures,
    }
    finished = subprocess.run(
        [NODE, "-e", _PAGE_DRIVER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(finished.stdout)


def run_page_scripts(scripts: list[str], run: PageRun) -> PageOutcome:
    outcome = _drive_page(scripts, run, [])
    return PageOutcome(outcome["attributes"], outcome["storage"])


def run_print_cycle(scripts: list[str], disclosures: list[bool]) -> PrintCycle:
    printed = _drive_page(scripts, PageRun(), disclosures)["printed"]
    return PrintCycle(tuple(printed["during"]), tuple(printed["after"]))


def call_script_function(script: str, name: str, argument: str) -> object:
    assert NODE is not None
    declaration = re.search(rf"^\t*function {name}\(.*?^\t\}}$", script, flags=re.DOTALL | re.MULTILINE)
    assert declaration is not None
    finished = subprocess.run(
        [NODE, "-e", _FUNCTION_DRIVER],
        input=json.dumps({"source": declaration.group(0), "call": name, "argument": argument}),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(finished.stdout)
