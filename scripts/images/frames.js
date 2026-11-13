const EXAMPLE_PATH = "../../examples/sales-pipeline.yaml";
const EXCERPT_LINES = 25;
const IMAGES = "../../docs/images";

const element = (tag, className, children = []) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children);
  return node;
};

const escapeHtml = (text) => text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

const highlightYamlLine = (line) =>
  escapeHtml(line)
    .replace(/"[^"]*"/g, (quoted) => `<span class="s">${quoted}</span>`)
    .replace(/(^\s*-?\s*|[{,]\s*)([a-z_]+)(?=:)/g, '$1<span class="k">$2</span>')
    .replace(/(:\s)(\d+)(?=[\s,}]|$)/g, '$1<span class="n">$2</span>')
    .replace(/(:\s)(true|false|green|amber|neutral|success|warning|heading|cards|callout|table)\b/g, '$1<span class="v">$2</span>');

const windowBar = (title, dark) =>
  element("div", dark ? "bar bar-dark" : "bar", [
    element("span", "dot"),
    element("span", "dot"),
    element("span", "dot"),
    element("span", "bar-title", [title]),
  ]);

const pageWindow = (title, image, dark, className) => {
  const picture = element("img", "shot");
  picture.src = `${IMAGES}/${image}`;
  picture.alt = "";
  return element("div", `window ${className}`, [windowBar(title, dark), picture]);
};

const editorWindow = async () => {
  const text = await fetch(EXAMPLE_PATH).then((response) => response.text());
  const code = element("pre", "code");
  code.innerHTML = text.split("\n").slice(0, EXCERPT_LINES).map(highlightYamlLine).join("\n");
  return element("div", "window editor", [windowBar("sales-pipeline.yaml", true), code]);
};

const wordmark = () => element("div", "wordmark", ["skaldr"]);

const renderHero = async (stage) => {
  document.body.classList.add("hero");
  stage.append(
    element("header", "hero-head", [
      wordmark(),
      element("p", "hero-line", ["One YAML file in. One polished, self-contained report page out."]),
    ]),
    element("div", "hero-flow", [
      await editorWindow(),
      element("div", "arrow", [element("span", "arrow-chip", ["skaldr sales-pipeline.yaml"]), element("span", "arrow-head", ["→"])]),
      pageWindow("Q3 Pipeline Review: West Region", "sales-light.png", false, "page-window"),
    ]),
  );
};

const renderSocial = (stage) => {
  document.body.classList.add("social");
  stage.append(
    element("section", "pitch", [
      wordmark(),
      element("p", "pitch-line", ["One YAML file in. One polished, self-contained report page out."]),
      element("code", "install", ["brew install alex-yanchenko/tap/skaldr"]),
      element("p", "repo", ["github.com/alex-yanchenko/skaldr"]),
    ]),
    element("section", "stack", [
      pageWindow("Q3 Warehouse Inventory Count", "warehouse-dark.png", true, "back"),
      pageWindow("Q3 Pipeline Review: West Region", "sales-light.png", false, "front"),
    ]),
  );
};

const stage = document.getElementById("stage");
if (location.hash === "#social") renderSocial(stage);
else void renderHero(stage);
