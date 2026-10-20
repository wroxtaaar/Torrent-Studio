// Usage: node graph.cjs <file> <Component> [--json]
// For every statement in a component body: line range, names it declares, and which names
// declared EARLIER in the component (or props) it reads. Used to find self-contained clusters.
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const [file, fname, flag] = process.argv.slice(2);
const src = fs.readFileSync(file, 'utf8');
const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
let fn = null;
for (const s of sf.statements) {
  if (ts.isFunctionDeclaration(s) && s.name && s.name.text === fname) fn = s;
  if (ts.isVariableStatement(s)) for (const d of s.declarationList.declarations)
    if (d.name.getText() === fname && d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer))) fn = d.initializer;
}
const L = n => sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
const E = n => sf.getLineAndCharacterOfPosition(n.getEnd()).line + 1;
const bind = (n, out) => { if (ts.isIdentifier(n)) out.push(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) bind(e.name, out); }); };
function declared(st) {
  const out = [];
  if (ts.isFunctionDeclaration(st) || ts.isTypeAliasDeclaration(st)) out.push(st.name.text);
  else if (ts.isVariableStatement(st)) st.declarationList.declarations.forEach(d => bind(d.name, out));
  return out;
}
function used(node) {
  const s = new Set();
  const v = n => {
    if (ts.isIdentifier(n)) {
      const p = n.parent;
      const prop = p && ((ts.isPropertyAccessExpression(p) && p.name === n) || (ts.isQualifiedName(p) && p.right === n) || (ts.isPropertyAssignment(p) && p.name === n) || (ts.isPropertySignature(p) && p.name === n) || (ts.isJsxAttribute(p) && p.name === n) || (ts.isMethodDeclaration(p) && p.name === n));
      if (!prop) s.add(n.text);
    }
    ts.forEachChild(n, v);
  };
  v(node); return s;
}
const params = []; fn.parameters.forEach(p => bind(p.name, params));
const defined = new Map(); params.forEach(p => defined.set(p, 'props'));
const rows = [];
for (const st of fn.body.statements) {
  const dec = declared(st);
  const u = [...used(st)].filter(x => defined.has(x) && !dec.includes(x));
  let kind = ts.SyntaxKind[st.kind].replace('Statement', '');
  if (ts.isExpressionStatement(st) && st.expression.getText().startsWith('useEffect')) kind = 'effect';
  if (ts.isExpressionStatement(st) && st.expression.getText().startsWith('useLayoutEffect')) kind = 'layoutEffect';
  rows.push({ a: L(st), b: E(st), kind, dec, uses: u });
  dec.forEach(d => defined.set(d, L(st)));
}
if (flag === '--json') console.log(JSON.stringify(rows));
else for (const r of rows) console.log(`${r.a}-${r.b} ${r.kind} [${r.dec.join(',')}] <- ${r.uses.join(',')}`);
