// Usage: node inner-candidates.cjs <file> <ComponentName>
// Lists statements inside a component body that do NOT depend on component scope
// (props, state, refs, other inner declarations that stay) and could become module-level code.
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const [file, fname] = process.argv.slice(2);
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
const scope = new Set();
for (const p of fn.parameters) { const w = n => { if (ts.isIdentifier(n)) scope.add(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) w(e.name); }); }; w(p.name); }
const stmts = fn.body.statements;
const owner = new Map();
for (const st of stmts) for (const n of declared(st)) { scope.add(n); owner.set(n, st); }
// candidate = declaration-like statement whose used names that are in scope are only itself or other candidates
const decl = stmts.filter(st => ts.isFunctionDeclaration(st) || ts.isTypeAliasDeclaration(st) || ts.isInterfaceDeclaration(st) ||
  (ts.isVariableStatement(st) && st.declarationList.declarations.every(d => d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer)))));
let cand = new Set(decl);
let changed = true;
while (changed) {
  changed = false;
  for (const st of [...cand]) {
    const own = new Set(declared(st));
    for (const u of used(st)) {
      if (own.has(u)) continue;
      if (scope.has(u)) {
        const o = owner.get(u);
        if (!o || !cand.has(o)) { cand.delete(st); changed = true; break; }
      }
    }
  }
}
for (const st of stmts) if (cand.has(st)) console.log(`${line(st)}-${endLine(st)}  ${endLine(st) - line(st) + 1}  ${declared(st).join(',')}`);
