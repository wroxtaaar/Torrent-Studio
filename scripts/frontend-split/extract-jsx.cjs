// Move one JSX child of a component's `return` into its own section component.
// The component must already take its state from one model hook: `const vm = useModel(...)` followed by
// `const { a, b, ... } = vm;` (see docs/frontend-split-plan.md, F5). The section receives `vm`.
// usage: extract-jsx.cjs plan|apply <src.tsx> <ModelHookFile> <NewName> <out.tsx> <A-B>
//   A-B = line range of one JSX child expression, e.g. `{isSearching && ( ... )}`
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const path = require('path');
const [mode, srcArg, modelArg, newName, outArg, rangeArg] = process.argv.slice(2);
if (!['plan', 'apply'].includes(mode) || !rangeArg) { console.error('usage: extract-jsx.cjs plan|apply <src.tsx> <modelFile.tsx> <Name> <out.tsx> <A-B>'); process.exit(2); }
const srcPath = path.resolve(srcArg), outPath = path.resolve(outArg), modelPath = path.resolve(modelArg);
const [A, B] = rangeArg.split('-').map(Number);
const text = fs.readFileSync(srcPath, 'utf8');
const lines = text.split('\n');
const sf = ts.createSourceFile(srcPath, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const rel = (from, to) => { let r = path.relative(path.dirname(from), to).split(path.sep).join('/'); return r.startsWith('.') ? r : './' + r; };

function used(node) {
  const set = new Set();
  const visit = n => {
    if (ts.isIdentifier(n)) {
      const p = n.parent;
      const prop = p && ((ts.isPropertyAccessExpression(p) && p.name === n) || (ts.isQualifiedName(p) && p.right === n) || (ts.isPropertyAssignment(p) && p.name === n) || (ts.isJsxAttribute(p) && p.name === n) || (ts.isPropertySignature(p) && p.name === n));
      if (!prop) set.add(n.text);
    }
    ts.forEachChild(n, visit);
  };
  visit(node); return set;
}
// the model destructure: `const { ... } = vm;`
let vmNames = null, fn = null;
sf.forEachChild(function find(n) {
  if (ts.isVariableDeclaration(n) && n.initializer && ts.isIdentifier(n.initializer) && n.initializer.text === 'vm' && ts.isObjectBindingPattern(n.name)) vmNames = new Set(n.name.elements.map(e => e.name.getText()));
  ts.forEachChild(n, find);
});
if (!vmNames) { console.error('no `const { ... } = vm;` found in the component'); process.exit(2); }
// snippet = whole lines A..B
const snippet = lines.slice(A - 1, B).join('\n');
const wrapper = `const __x = () => (<>\n${snippet}\n</>);`;
const wsf = ts.createSourceFile('x.tsx', wrapper, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const tokens = used(wsf);
// sanity: balanced JSX child
const diags = wsf.parseDiagnostics || [];
if (diags.length) { console.error('range is not a balanced JSX child: ' + ts.flattenDiagnosticMessageText(diags[0].messageText, '\n')); process.exit(2); }
const need = [...tokens].filter(n => vmNames.has(n)).sort();
// imports of the source that the snippet uses
const impLines = [];
for (const st of sf.statements) if (ts.isImportDeclaration(st)) {
  const c = st.importClause; if (!c) continue;
  const spec = st.moduleSpecifier.text;
  const newSpec = spec.startsWith('.') ? rel(outPath, path.resolve(path.dirname(srcPath), spec)) : spec;
  const parts = [];
  if (c.name && tokens.has(c.name.text)) parts.push(c.name.text);
  let named = [];
  if (c.namedBindings && ts.isNamespaceImport(c.namedBindings) && tokens.has(c.namedBindings.name.text)) parts.push('* as ' + c.namedBindings.name.text);
  if (c.namedBindings && ts.isNamedImports(c.namedBindings)) named = c.namedBindings.elements.filter(e => tokens.has(e.name.text)).map(e => e.getText(sf));
  if (named.length) parts.push('{ ' + named.join(', ') + ' }');
  if (parts.length) impLines.push(`import ${c.isTypeOnly ? 'type ' : ''}${parts.join(', ')} from '${newSpec}';`);
}
const importedAll = new Set(); for (const l of impLines) (l.match(/[A-Za-z_$][\w$]*/g) || []).forEach(x => importedAll.add(x));
const modelRel = rel(outPath, modelPath);
const body = `export function ${newName}({ vm }: { vm: PanelModel }) {\n  const { ${need.join(', ')} } = vm;\n  return (\n    <>\n${snippet}\n    </>\n  );\n}\n`;
const outText = `${impLines.join('\n')}${impLines.length ? '\n' : ''}import type { PanelModel } from '${modelRel}';\n\n${body}`;
const indent = (lines[A - 1].match(/^\s*/) || [''])[0];
console.log(`${newName}: lines ${A}-${B} (${B - A + 1}), needs ${need.length} model name(s), ${impLines.length} import(s)`);
if (mode === 'plan') process.exit(0);
if (fs.existsSync(outPath)) { console.error(outPath + ' exists'); process.exit(2); }
fs.writeFileSync(outPath, outText);
const srcLines = [...lines.slice(0, A - 1), `${indent}<${newName} vm={vm} />`, ...lines.slice(B)];
let src2 = srcLines.join('\n');
const imp = `import { ${newName} } from '${rel(srcPath, outPath)}';`;
const sf2 = ts.createSourceFile(srcPath, src2, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const last = sf2.statements.filter(s => ts.isImportDeclaration(s)).pop();
src2 = src2.slice(0, last.getEnd()) + '\n' + imp + src2.slice(last.getEnd());
// prune imports the move made unused
const sf3 = ts.createSourceFile(srcPath, src2, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const usedAfter = new Set(); sf3.statements.filter(s => !ts.isImportDeclaration(s)).forEach(s => used(s).forEach(x => usedAfter.add(x)));
for (const st of sf3.statements.filter(s => ts.isImportDeclaration(s)).reverse()) {
  const c = st.importClause; if (!c) continue;
  const def = c.name && usedAfter.has(c.name.text) ? c.name.text : null;
  let ns = null, named = [];
  if (c.namedBindings && ts.isNamespaceImport(c.namedBindings)) ns = usedAfter.has(c.namedBindings.name.text) ? c.namedBindings.name.text : null;
  if (c.namedBindings && ts.isNamedImports(c.namedBindings)) named = c.namedBindings.elements.filter(e => usedAfter.has(e.name.text));
  const total = (c.name ? 1 : 0) + (c.namedBindings ? (ts.isNamespaceImport(c.namedBindings) ? 1 : c.namedBindings.elements.length) : 0);
  const keep = (def ? 1 : 0) + (ns ? 1 : 0) + named.length;
  if (keep === total) continue;
  // only touch imports this move emptied (the snippet used them)
  const was = [c.name && c.name.text, ...(c.namedBindings && ts.isNamedImports(c.namedBindings) ? c.namedBindings.elements.filter(e => !usedAfter.has(e.name.text)).map(e => e.name.text) : [])].filter(Boolean);
  if (!was.some(x => tokens.has(x))) continue;
  const parts = []; if (def) parts.push(def); if (ns) parts.push('* as ' + ns); if (named.length) parts.push('{ ' + named.map(e => e.getText(sf3)).join(', ') + ' }');
  const repl = keep ? `import ${c.isTypeOnly ? 'type ' : ''}${parts.join(', ')} from ${st.moduleSpecifier.getText(sf3)};` : '';
  const e0 = st.getEnd();
  src2 = src2.slice(0, st.getStart(sf3)) + repl + src2.slice(e0 + (repl ? 0 : (src2[e0] === '\n' ? 1 : 0)));
}
fs.writeFileSync(srcPath, src2);
console.log(`ok: wrote ${path.relative(process.cwd(), outPath)}; ${path.basename(srcPath)} now ${src2.split('\n').length} lines`);
