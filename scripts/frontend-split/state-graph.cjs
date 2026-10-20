// Usage: node state-graph.cjs <file> <Component> [--json]
// For every statement in the component body: what it declares and which earlier statements it depends on.
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
const line = n => sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
const endLine = n => sf.getLineAndCharacterOfPosition(n.getEnd()).line + 1;
function declared(st) {
  const out = [];
  if (ts.isFunctionDeclaration(st) || ts.isTypeAliasDeclaration(st) || ts.isInterfaceDeclaration(st)) out.push(st.name.text);
  else if (ts.isVariableStatement(st)) for (const d of st.declarationList.declarations) {
    const w = n => { if (ts.isIdentifier(n)) out.push(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) w(e.name); }); };
    w(d.name);
  }
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
  v(node);
  return s;
}
const params = new Set();
for (const p of fn.parameters) { const w = n => { if (ts.isIdentifier(n)) params.add(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) w(e.name); }); }; w(p.name); }
const stmts = fn.body.statements;
const owner = new Map();
stmts.forEach((st, i) => declared(st).forEach(n => owner.set(n, i)));
const rows = stmts.map((st, i) => {
  const u = used(st);
  const own = new Set(declared(st));
  const deps = new Set();
  const usesProps = [];
  for (const n of u) {
    if (own.has(n)) continue;
    if (owner.has(n) && owner.get(n) !== i) deps.add(owner.get(n));
    else if (params.has(n)) usesProps.push(n);
  }
  const kind = ts.isReturnStatement(st) ? 'return' : ts.isExpressionStatement(st) ? 'effect' : ts.isIfStatement(st) ? 'if' : 'decl';
  return { i, a: line(st), b: endLine(st), kind, declares: declared(st), deps: [...deps].sort((x, y) => x - y), props: usesProps,
           text: kind === 'effect' ? st.expression.getText().slice(0, 40).replace(/\s+/g, ' ') : '' };
});
if (flag === '--json') { console.log(JSON.stringify(rows)); process.exit(0); }
for (const r of rows) console.log(`${String(r.i).padStart(3)} ${String(r.a).padStart(5)}-${String(r.b).padEnd(5)} ${r.kind.padEnd(6)} ${(r.declares.join(',') || r.text).slice(0, 60).padEnd(60)} <- ${r.deps.join(',')}${r.props.length ? ' P:' + r.props.join(',') : ''}`.slice(0, 200));
