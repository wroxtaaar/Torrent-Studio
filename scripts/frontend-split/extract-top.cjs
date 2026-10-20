// Move top-level statements of a .ts/.tsx file into a new module and fix imports on both sides.
//
//   node extract-top.cjs plan  <src-file> <new-module> <A-B[,C-D...]>
//   node extract-top.cjs apply <src-file> <new-module> <A-B[,C-D...]>
//   ... <A-B,...> <ComponentName>   -> take the statements from INSIDE that component's body (see
//                                      inner-candidates.cjs); they are dedented and exported.
//
// * line ranges are 1-based lines of the CURRENT source file (use outline.cjs); every top-level
//   statement whose first line lies in a range is moved (with its leading comments if they are
//   inside the range).
// * the new module gets the imports it needs (relative paths are rewritten), every moved
//   declaration is exported, the source file imports back what it still uses, and imports the
//   source no longer needs are dropped.
// * it refuses (like scripts/refactor/extract.py) when a moved statement uses a top-level name
//   that stays behind (that would be a circular import) - move that name too.
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const path = require('path');

const [mode, srcArg, modArg, rangesArg, componentName] = process.argv.slice(2);
if (!['plan', 'apply'].includes(mode) || !rangesArg) {
  console.error('usage: extract-top.cjs plan|apply <src-file> <new-module> <A-B,...>');
  process.exit(2);
}
const srcPath = path.resolve(srcArg);
const modPath = path.resolve(modArg);
const ranges = rangesArg.split(',').map(r => r.split('-').map(Number));
const inRange = line => ranges.some(([a, b]) => line >= a && line <= b);

const text = fs.readFileSync(srcPath, 'utf8');
const lines = text.split('\n');
const sf = ts.createSourceFile(srcPath, text, ts.ScriptTarget.Latest, true, srcPath.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
const lineOf = pos => sf.getLineAndCharacterOfPosition(pos).line + 1;

// ---- top-level statements ------------------------------------------------
function declaredNames(st) {
  const out = [];
  if (ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st) || ts.isInterfaceDeclaration(st) ||
      ts.isTypeAliasDeclaration(st) || ts.isEnumDeclaration(st)) { if (st.name) out.push(st.name.text); }
  else if (ts.isVariableStatement(st)) {
    for (const d of st.declarationList.declarations) {
      const walk = n => {
        if (ts.isIdentifier(n)) out.push(n.text);
        else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) walk(e.name); });
      };
      walk(d.name);
    }
  }
  return out;
}
const imports = [];   // {st, defaultName, named:[{name,alias,typeOnly}], ns, spec, typeOnly}
const tops = [];      // non-import statements
for (const st of sf.statements) {
  if (ts.isImportDeclaration(st)) {
    const clause = st.importClause;
    const rec = { st, spec: st.moduleSpecifier.text, typeOnly: !!(clause && clause.isTypeOnly), defaultName: null, named: [], ns: null, sideEffect: !clause };
    if (clause) {
      if (clause.name) rec.defaultName = clause.name.text;
      if (clause.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) rec.ns = clause.namedBindings.name.text;
        else for (const e of clause.namedBindings.elements) rec.named.push({ name: (e.propertyName || e.name).text, local: e.name.text, typeOnly: e.isTypeOnly });
      }
    }
    imports.push(rec);
  } else tops.push(st);
}
let moved = [], staying = [];
let paramNames = [];
if (componentName) {
  let fn = null;
  for (const s of sf.statements) {
    if (ts.isFunctionDeclaration(s) && s.name && s.name.text === componentName) fn = s;
    if (ts.isVariableStatement(s)) for (const d of s.declarationList.declarations)
      if (d.name.getText() === componentName && d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer))) fn = d.initializer;
  }
  if (!fn) { console.error('component not found: ' + componentName); process.exit(2); }
  const w = n => { if (ts.isIdentifier(n)) paramNames.push(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) w(e.name); }); };
  fn.parameters.forEach(p => w(p.name));
  for (const st of fn.body.statements) (inRange(lineOf(st.getStart())) ? moved : staying).push(st);
  staying.push(...tops);   // top-level code that stays behind is also unavailable to the new module
} else {
  for (const st of tops) {
    const start = lineOf(st.getStart());
    (inRange(start) ? moved : staying).push(st);
  }
}
if (!moved.length) { console.error('nothing selected'); process.exit(2); }

// ---- identifier usage (name based, deliberately conservative) -------------
function usedNames(nodes) {
  const used = new Set();
  const visit = n => {
    if (ts.isIdentifier(n)) {
      const p = n.parent;
      const isPropName = p && ((ts.isPropertyAccessExpression(p) && p.name === n) || (ts.isQualifiedName(p) && p.right === n) ||
        (ts.isPropertyAssignment(p) && p.name === n) || (ts.isPropertySignature(p) && p.name === n) ||
        (ts.isJsxAttribute(p) && p.name === n) || (ts.isMethodDeclaration(p) && p.name === n));
      if (!isPropName) used.add(n.text);
    }
    ts.forEachChild(n, visit);
  };
  nodes.forEach(visit);
  return used;
}
// shorthand `{ foo }` in an object literal uses `foo`; the visitor above already counts it (Identifier is the name).

const movedNames = new Set(moved.flatMap(declaredNames));
const stayingNames = new Set([...staying.flatMap(declaredNames), ...paramNames]);
const usedByMoved = usedNames(moved);

// moved code that needs something which stays
const blockers = [];
for (const name of usedByMoved) if (stayingNames.has(name) && !movedNames.has(name)) {
  const st = staying.find(s => declaredNames(s).includes(name));
  if (!st) { blockers.push(`${name} is a parameter (prop) of ${componentName}; it cannot be used by moved code`); continue; }
  blockers.push(`${name} (line ${lineOf(st.getStart())}) is used by the moved code but stays in ${path.basename(srcPath)}; move it too`);
}
if (blockers.length) { console.log('cannot move yet:\n  - ' + blockers.join('\n  - ')); process.exit(1); }

// ---- build new module ------------------------------------------------------
const relFrom = (fromFile, target) => {
  let r = path.relative(path.dirname(fromFile), target).split(path.sep).join('/');
  if (!r.startsWith('.')) r = './' + r;
  return r;
};
function rewriteSpec(spec, fromSrc, toNew) {
  if (!spec.startsWith('.')) return spec;
  const abs = path.resolve(path.dirname(fromSrc), spec);
  return relFrom(toNew, abs);
}
const needed = []; // import statements for new module
for (const imp of imports) {
  if (imp.sideEffect) continue;
  const named = imp.named.filter(n => usedByMoved.has(n.local));
  const def = imp.defaultName && usedByMoved.has(imp.defaultName) ? imp.defaultName : null;
  const ns = imp.ns && usedByMoved.has(imp.ns) ? imp.ns : null;
  if (!named.length && !def && !ns) continue;
  const spec = rewriteSpec(imp.spec, srcPath, modPath);
  const parts = [];
  if (def) parts.push(def);
  if (ns) parts.push(`* as ${ns}`);
  if (named.length) parts.push('{ ' + named.map(n => (n.typeOnly ? 'type ' : '') + (n.name === n.local ? n.name : `${n.name} as ${n.local}`)).join(', ') + ' }');
  needed.push(`import ${imp.typeOnly ? 'type ' : ''}${parts.join(', ')} from '${spec}';`);
}

// moved text: whole lines from the first to the last moved line of each contiguous selection
const chunks = [];
for (const st of moved) {
  // include leading comment lines that sit directly above the statement and inside a range
  let startLine = lineOf(st.getStart());
  while (startLine - 1 >= 1 && inRange(startLine - 1) && /^\s*(\/\/|\/\*|\*)/.test(lines[startLine - 2]) ) startLine--;
  const endLine = lineOf(st.getEnd());
  chunks.push({ startLine, endLine, st });
}
let body = '';
let prevEnd = 0;
for (const c of chunks) {
  let block = lines.slice(c.startLine - 1, c.endLine).join('\n');
  const names = declaredNames(c.st);
  if (componentName) block = block.split('\n').map(l => l.replace(/^ {1,2}/, '')).join('\n');
  const hasExport = (ts.getCombinedModifierFlags(c.st) & ts.ModifierFlags.Export) !== 0;
  if (!hasExport && names.length) {
    // add `export ` in front of the declaration keyword (after leading comments)
    const stLine = lineOf(c.st.getStart());
    const idx = stLine - c.startLine;
    const arr = block.split('\n');
    arr[idx] = arr[idx].replace(/^(\s*)/, '$1export ');
    block = arr.join('\n');
  }
  body += (prevEnd && c.startLine - prevEnd > 1 ? '\n' : '') + (body ? '\n' : '') + block + '\n';
  prevEnd = c.endLine;
}
const newModule = (needed.length ? needed.join('\n') + '\n\n' : '') + body.replace(/^\n+/, '');

// ---- rewrite the source ------------------------------------------------------
const removedLines = new Set();
for (const c of chunks) for (let l = c.startLine; l <= c.endLine; l++) removedLines.add(l);
let kept = lines.filter((_, i) => !removedLines.has(i + 1));
// collapse runs of >2 blank lines left behind
const collapsed = [];
for (const l of kept) {
  if (l.trim() === '' && collapsed.length >= 2 && collapsed[collapsed.length - 1].trim() === '' && collapsed[collapsed.length - 2].trim() === '') continue;
  collapsed.push(l);
}
let srcAfter = collapsed.join('\n');

// what does the remaining source still use?
const sfAfter = ts.createSourceFile(srcPath, srcAfter, ts.ScriptTarget.Latest, true, sf.scriptKind);
const stillUsed = usedNames(sfAfter.statements.filter(s => !ts.isImportDeclaration(s)));
const importBack = [...movedNames].filter(n => stillUsed.has(n)).sort();

// drop imports the remaining source no longer needs (only ones that became unused through this move)
const sfStmts = sfAfter.statements.filter(s => ts.isImportDeclaration(s));
let rebuilt = srcAfter;
for (const st of sfStmts.slice().reverse()) {
  const clause = st.importClause;
  if (!clause) continue;
  const def = clause.name && stillUsed.has(clause.name.text) ? clause.name.text : null;
  let ns = null, named = [];
  if (clause.namedBindings) {
    if (ts.isNamespaceImport(clause.namedBindings)) ns = stillUsed.has(clause.namedBindings.name.text) ? clause.namedBindings.name.text : null;
    else named = clause.namedBindings.elements.filter(e => stillUsed.has(e.name.text));
  }
  const total = (clause.name ? 1 : 0) + (clause.namedBindings ? (ts.isNamespaceImport(clause.namedBindings) ? 1 : clause.namedBindings.elements.length) : 0);
  const keep = (def ? 1 : 0) + (ns ? 1 : 0) + named.length;
  if (keep === total) continue;
  // only prune when the original (pre-move) file used the dropped specifier in moved code (never touch pre-existing unused ones)
  const droppedUsedByMoved = [
    clause.name && !def && usedByMoved.has(clause.name.text),
    ...(clause.namedBindings && !ts.isNamespaceImport(clause.namedBindings) ? clause.namedBindings.elements.filter(e => !stillUsed.has(e.name.text)).map(e => usedByMoved.has(e.name.text)) : []),
  ].some(Boolean);
  if (!droppedUsedByMoved) continue;
  const start = st.getStart(sfAfter), end = st.getEnd();
  let repl = '';
  if (keep) {
    const parts = [];
    if (def) parts.push(def);
    if (ns) parts.push(`* as ${ns}`);
    if (named.length) parts.push('{ ' + named.map(e => e.getText(sfAfter)).join(', ') + ' }');
    repl = `import ${clause.isTypeOnly ? 'type ' : ''}${parts.join(', ')} from ${st.moduleSpecifier.getText(sfAfter)};`;
  }
  rebuilt = rebuilt.slice(0, start) + repl + rebuilt.slice(end + (repl ? 0 : (rebuilt[end] === '\n' ? 1 : 0)));
}
srcAfter = rebuilt;

if (importBack.length) {
  const spec = relFrom(srcPath, modPath).replace(/\.tsx?$/, (m) => m); // keep extension: repo uses explicit .ts/.tsx imports
  const stmt = `import { ${importBack.join(', ')} } from '${spec}';`;
  const sf2 = ts.createSourceFile(srcPath, srcAfter, ts.ScriptTarget.Latest, true, sf.scriptKind);
  const lastImport = sf2.statements.filter(s => ts.isImportDeclaration(s)).pop();
  const pos = lastImport ? lastImport.getEnd() : 0;
  srcAfter = srcAfter.slice(0, pos) + (lastImport ? '\n' : '') + stmt + (lastImport ? '' : '\n') + srcAfter.slice(pos);
}

console.log(`selected ${moved.length} statements, ~${removedLines.size} lines -> ${path.relative(process.cwd(), modPath)}`);
console.log(`new module imports ${needed.length} module(s); ${path.basename(srcPath)} imports back ${importBack.length} name(s)`);
if (mode === 'plan') { console.log('(plan only; nothing written)'); process.exit(0); }

if (fs.existsSync(modPath)) { console.error(`${modPath} exists; pick another name`); process.exit(2); }
fs.mkdirSync(path.dirname(modPath), { recursive: true });
fs.writeFileSync(modPath, newModule);
fs.writeFileSync(srcPath, srcAfter);
console.log(`ok: wrote ${path.relative(process.cwd(), modPath)} (${newModule.split('\n').length} lines), ${path.basename(srcPath)} now ${srcAfter.split('\n').length} lines`);
