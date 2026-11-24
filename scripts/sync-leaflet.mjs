// Copy the pinned Leaflet distribution into static/vendor/leaflet.
import fs from "node:fs";
import path from "node:path";

const source = path.join("node_modules", "leaflet");
const destination = path.join("static", "vendor", "leaflet");

fs.mkdirSync(destination, { recursive: true });
for (const file of ["leaflet.js", "leaflet.css", "images"]) {
  fs.cpSync(path.join(source, "dist", file), path.join(destination, file), {
    recursive: true,
  });
}
fs.copyFileSync(
  path.join(source, "LICENSE"),
  path.join(destination, "LICENSE"),
);

// The source map is not shipped, and a dangling reference breaks collectstatic.
const script = path.join(destination, "leaflet.js");
fs.writeFileSync(
  script,
  fs
    .readFileSync(script, "utf8")
    .replace(/\r?\n\/\/# sourceMappingURL=.*\s*$/, ""),
);