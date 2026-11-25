(() => {
  const treeElement = document.getElementById("issue-tree");
  const container = document.getElementById("issue-path");
  const original = document.getElementById("id_reported_issue_type");
  if (!treeElement || !container || !original) return;

  const nodes = JSON.parse(treeElement.textContent);
  const byId = new Map(nodes.map((node) => [String(node.id), node]));
  const children = new Map();
  for (const node of nodes) {
    const parent = node.parent_id === null ? "" : String(node.parent_id);
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(node);
  }
  for (const entries of children.values()) {
    entries.sort((a, b) => a.name.localeCompare(b.name));
  }

  function selectedPath() {
    const path = [];
    const visited = new Set();
    let node = byId.get(original.value);
    while (node && !visited.has(String(node.id))) {
      visited.add(String(node.id));
      path.unshift(String(node.id));
      node = byId.get(String(node.parent_id));
    }
    return path;
  }

  function render(path) {
    container.replaceChildren();
    let parent = "";
    let depth = 0;
    const visited = new Set();
    while (children.has(parent) && !visited.has(parent)) {
      visited.add(parent);
      const wrapper = document.createElement("div");
      wrapper.className = "ui-field";
      const select = document.createElement("select");
      select.className = "ui-select";
      select.id = `issue-path-${depth}`;
      const label = document.createElement("label");
      label.className = "ui-label";
      label.htmlFor = select.id;
      label.textContent = depth === 0 ? "What is the issue about?" : "Choose a more specific issue";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Choose an option";
      select.append(placeholder);
      for (const node of children.get(parent)) {
        const option = document.createElement("option");
        option.value = String(node.id);
        option.textContent = node.name;
        select.append(option);
      }
      select.value = path[depth] || "";
      if (original.getAttribute("aria-invalid") === "true") {
        select.setAttribute("aria-invalid", "true");
        select.setAttribute("aria-describedby", "id_reported_issue_type_error");
      }
      const level = depth;
      select.addEventListener("change", () => {
        const nextPath = path.slice(0, level);
        if (select.value) nextPath.push(select.value);
        original.value = nextPath.at(-1) || "";
        render(nextPath);
        container.querySelector(`#issue-path-${level}`)?.focus();
      });
      wrapper.append(label, select);
      container.append(wrapper);
      if (!select.value) break;
      parent = select.value;
      depth += 1;
    }
  }

  const path = selectedPath();
  // Keep the original field available if the saved hierarchy cannot be displayed.
  if (original.value && path[0] && byId.get(path[0]).parent_id !== null) return;
  if (!children.has("")) return;
  render(path);
  original.hidden = true;
  const label = original.closest("[data-field]")?.querySelector("label");
  if (label) label.hidden = true;
})();
