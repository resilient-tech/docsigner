// Generates opensigner.iife.js from opensigner.js. Run: node build-iife.js

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const src = readFileSync(here + "opensigner.js", "utf8").replaceAll("export class ", "class ");

writeFileSync(here + "opensigner.iife.js",
`// Generated from opensigner.js by build-iife.js. Do not edit by hand.
(() => {
${src}
window.OpenSigner = OpenSigner;
window.OpenSignerError = OpenSignerError;
})();
`);
console.log("wrote opensigner.iife.js");
