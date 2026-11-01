import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const site = join(root, 'site');
const failures = [];
const required = ['index.html', 'styles.css', 'app.js', 'sw.js', 'manifest.webmanifest', 'icon.svg', 'data/recipes.json'];

for (const file of required) {
  if (!existsSync(join(site, file))) failures.push(`Missing required site file: ${file}`);
}

for (const file of ['app.js', 'sw.js']) {
  try { execFileSync(process.execPath, ['--check', join(site, file)], { stdio: 'pipe' }); }
  catch (error) { failures.push(`${file} failed node --check: ${error.stderr?.toString() || error.message}`); }
}

const html = readFileSync(join(site, 'index.html'), 'utf8');
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
for (const match of html.matchAll(/href="#([^"]+)"/g)) {
  if (match[1] && !ids.has(match[1])) failures.push(`Unresolved internal anchor: #${match[1]}`);
}
for (const match of html.matchAll(/(?:href|src)="(\.\/[^"?#]+)/g)) {
  const asset = match[1].replace(/^\.\//, '');
  if (!existsSync(join(site, asset))) failures.push(`Missing referenced asset: ${asset}`);
}
if (!html.includes('Content-Security-Policy')) failures.push('Missing Content Security Policy');
if (/\son\w+\s*=/.test(html)) failures.push('Inline event handler found in index.html');

let catalog;
try { catalog = JSON.parse(readFileSync(join(site, 'data/recipes.json'), 'utf8')); }
catch (error) { failures.push(`Invalid recipe JSON: ${error.message}`); }

if (catalog) {
  if (catalog.count !== catalog.recipes?.length) failures.push('Catalog count does not match recipes length');
  if (!catalog.count || catalog.count < 1) failures.push('Catalog is empty');
  const idsSeen = new Set();
  for (const recipe of catalog.recipes || []) {
    for (const key of ['id', 'title', 'category', 'status']) if (!recipe[key]) failures.push(`Recipe missing ${key}: ${recipe.title || '(untitled)'}`);
    if (idsSeen.has(recipe.id)) failures.push(`Duplicate recipe id: ${recipe.id}`);
    idsSeen.add(recipe.id);
  }
}

function filesIn(directory) {
  return readdirSync(directory).flatMap(name => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? filesIn(path) : [path];
  });
}

const publicText = filesIn(site)
  .filter(file => ['.html', '.css', '.js', '.json', '.webmanifest', '.svg'].includes(extname(file)))
  .map(file => readFileSync(file, 'utf8'))
  .join('\n');
const privateSignals = [
  ['/home path', /\/home\/[A-Za-z0-9._-]+\//],
  ['Obsidian wikilink', /\[\[[^\]]+\]\]/],
  ['credential-like value', /(?:token|api[_-]?key|password|secret)["']?\s*[:=]\s*["']?[^\s,"']{8,}/i],
  ['private key', /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
  ['email address', /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i],
];
for (const [label, pattern] of privateSignals) if (pattern.test(publicText)) failures.push(`Public artifact contains ${label}`);

if (failures.length) {
  console.error(`Validation failed with ${failures.length} problem(s):\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`Validated ${required.length} critical assets, ${catalog.count} recipes, unique ids, anchors, JavaScript syntax, CSP, and public-data boundary.`);
