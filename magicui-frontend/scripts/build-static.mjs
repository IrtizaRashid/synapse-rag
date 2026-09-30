import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const root = import.meta.dirname;
const outDir = resolve(root, "../../static/magicui");

mkdirSync(outDir, { recursive: true });
copyFileSync(resolve(root, "../src/static-magicui.js"), resolve(outDir, "magicui.js"));
copyFileSync(resolve(root, "../src/styles.css"), resolve(outDir, "magicui.css"));

console.log(`Built Magic UI assets in ${outDir}`);
