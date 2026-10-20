// Move statements out of a React component body into a custom hook module.
//
//   node extract-hook.cjs plan  <src.tsx> <Component> <useHookName> <out.ts> <A-B[,C-D...]>
//   node extract-hook.cjs apply <src.tsx> <Component> <useHookName> <out.ts> <A-B[,C-D...]>
//
// * ranges are 1-based lines of the CURRENT source; every statement of the component body whose
//   first line is inside a range is moved (comment lines directly above it travel with it).
// * the hook is `export function useHookName() { <statements>; return { names used elsewhere }; }`
//   and the component gets `const { names } = useHookName();` at the position of the first moved
//   statement, so React's hook order only changes for independent state hooks.
// * allowed: statements that depend only on imports / module-level code of OTHER modules and on
//   each other. Refused (with the reason): uses of component props, of body statements that
//   stay behind, or of top-level code in the source file that stays (would be circular).
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const path = require('path');

const [mode, srcArg, compName, hookName, outArg, rangesArg] = process.argv.slice(2);
if (!['plan', 'apply'].includes(mode) || !rangesArg) {
  console.error('usage: extract-hook.cjs plan|apply <src.tsx> <Component> <useHook> <out.ts> <A-B,...>');
  process.exit(2);
}
const srcPath = path.resolve(srcArg), outPath = path.resolve(outArg);
const ranges = rangesArg.split(',').map(r => r.split('-').map(Number));
const inRange = l => ranges.some(([a, b]) => l >= a && l <= b);
const text = fs.readFileSync(srcPath, 'utf8');
const lines = text.split('\n');
const kind = srcPath.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
const sf = ts.createSourceFile(srcPath, text, ts.ScriptTarget.Latest, true, kind);
const lineOf = p => sf.getLineAndCharacterOfPosition(p).line + 1;

function declaredNames(st) {
  const out = [];
  if (ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st) || ts.isInterfaceDeclaration(st) || ts.isTypeAliasDeclaration(st)) { if (st.name) out.push(st.name.text); }
  else if (ts.isVariableStatement(st)) for (const d of st.declarationList.declarations) {
    const w = n => { if (ts.isIdentifier(n)) out.push(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) w(e.name); }); };
    w(d.name);
  }
  return out;
}
function usedNames(nodes) {
  const used = new Set();
  const visit = n => {
    if (ts.isIdentifier(n)) {
      const p = n.parent;
      const prop = p && ((ts.isPropertyAccessExpression(p) && p.name === n) || (ts.isQualifiedName(p) && p.right === n) || (ts.isPropertyAssignment(p) && p.name === n) || (ts.isPropertySignature(p) && p.name === n) || (ts.isJsxAttribute(p) && p.name === n) || (ts.isMethodDeclaration(p) && p.name === n));
      if (!prop) used.add(n.text);
    }
    ts.forEachChild(n, visit);
  };
  nodes.forEach(visit);
  return used;
}

// ---- locate component, imports, top-level code -------------------------------
let fn = null;
for (const s of sf.statements) {
  if (ts.isFunctionDeclaration(s) && s.name && s.name.text === compName) fn = s;
  if (ts.isVariableStatement(s)) for (const d of s.declarationList.declarations)
    if (d.name.getText() === compName && d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer))) fn = d.initializer;
}
if (!fn) { console.error('component not found'); process.exit(2); }
const imports = [], topLevel = [];
for (const st of sf.statements) {
  if (ts.isImportDeclaration(st)) {
    const c = st.importClause;
    imports.push({ st, spec: st.moduleSpecifier.text, typeOnly: !!(c && c.isTypeOnly), def: c && c.name ? c.name.text : null,
      ns: c && c.namedBindings && ts.isNamespaceImport(c.namedBindings) ? c.namedBindings.name.text : null,
      named: c && c.namedBindings && ts.isNamedImports(c.namedBindings) ? c.namedBindings.elements.map(e => ({ name: (e.propertyName || e.name).text, local: e.name.text, typeOnly: e.isTypeOnly })) : [] });
  } else topLevel.push(st);
}
const propNames = new Set();
for (const p of fn.parameters) { const w = n => { if (ts.isIdentifier(n)) propNames.add(n.text); else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) w(e.name); }); }; w(p.name); }

// props type (React.FC<Props>) and which props have a default value in the parameter destructuring
let propsType = null;
{
  for (const st of sf.statements) if (ts.isVariableStatement(st)) for (const d of st.declarationList.declarations)
    if (d.initializer === fn && d.type && ts.isTypeReferenceNode(d.type) && d.type.typeArguments && d.type.typeArguments.length) propsType = d.type.typeArguments[0].getText();
}
const propHasDefault = new Set();
for (const p of fn.parameters) if (ts.isObjectBindingPattern(p.name)) p.name.elements.forEach(e => { if (e.initializer && ts.isIdentifier(e.name)) propHasDefault.add(e.name.text); });

const body = fn.body.statements;
const moved = body.filter(st => inRange(lineOf(st.getStart())));
const staying = body.filter(st => !moved.includes(st));
if (!moved.length) { console.error('nothing selected'); process.exit(2); }
const movedNames = new Set(moved.flatMap(declaredNames));
const stayingBodyNames = new Map();
staying.forEach(st => declaredNames(st).forEach(n => stayingBodyNames.set(n, st)));
const stayingTopNames = new Map();
topLevel.forEach(st => declaredNames(st).forEach(n => stayingTopNames.set(n, st)));
const usedByMoved = usedNames(moved);

// where do the names declared by staying body statements come from?
const hookOf = new Map();   // local name -> hook function that returned it
body.forEach(st => {
  if (!ts.isVariableStatement(st)) return;
  for (const d of st.declarationList.declarations) {
    if (ts.isObjectBindingPattern(d.name) && d.initializer && ts.isCallExpression(d.initializer) && ts.isIdentifier(d.initializer.expression) && /^use[A-Z]/.test(d.initializer.expression.text))
      d.name.elements.forEach(e => { if (ts.isIdentifier(e.name)) hookOf.set(e.name.text, d.initializer.expression.text); });
  }
});
const blockers = [];
const inputsByHook = new Map();   // hook -> [names]
const propInputs = [];
for (const n of usedByMoved) {
  if (movedNames.has(n)) continue;
  if (hookOf.has(n) && stayingBodyNames.has(n) && !moved.includes(stayingBodyNames.get(n))) { const h = hookOf.get(n); (inputsByHook.get(h) || inputsByHook.set(h, []).get(h)).push(n); }
  else if (propNames.has(n) && !stayingBodyNames.has(n)) propInputs.push(n);
  else if (stayingBodyNames.has(n)) blockers.push(`${n} (line ${lineOf(stayingBodyNames.get(n).getStart())}) is declared directly in the component and stays there; move it too or put it in a hook first`);
  else if (stayingTopNames.has(n)) blockers.push(`${n} (line ${lineOf(stayingTopNames.get(n).getStart())}) is top-level code of ${path.basename(srcPath)} and would become a circular import; move it to its own module first`);
}
if (propInputs.length && !propsType) blockers.push(`uses props (${propInputs.join(', ')}) but the component has no React.FC<Props> annotation to type them`);
if (blockers.length) { console.log('cannot move yet:\n  - ' + blockers.join('\n  - ')); process.exit(1); }

// ---- build hook module --------------------------------------------------------
const rel = (from, to) => { let r = path.relative(path.dirname(from), to).split(path.sep).join('/'); return r.startsWith('.') ? r : './' + r; };
const importLines = [];
const extraNames = new Set([...inputsByHook.keys(), ...(propInputs.length && propsType ? [propsType] : [])]);
for (const imp of imports) {
  if (!imp.def && !imp.ns && !imp.named.length) continue;
  const need = n => usedByMoved.has(n) || extraNames.has(n);
  const named = imp.named.filter(n => need(n.local));
  const def = imp.def && need(imp.def) ? imp.def : null;
  const ns = imp.ns && need(imp.ns) ? imp.ns : null;
  if (!named.length && !def && !ns) continue;
  let spec = imp.spec;
  if (spec.startsWith('.')) spec = rel(outPath, path.resolve(path.dirname(srcPath), spec));
  const parts = [];
  if (def) parts.push(def);
  if (ns) parts.push('* as ' + ns);
  if (named.length) parts.push('{ ' + named.map(n => (n.typeOnly ? 'type ' : '') + (n.name === n.local ? n.name : `${n.name} as ${n.local}`)).join(', ') + ' }');
  importLines.push(`import ${imp.typeOnly ? 'type ' : ''}${parts.join(', ')} from '${spec}';`);
}
// leading comments directly above a moved statement travel with it
const chunks = moved.map(st => {
  let a = lineOf(st.getStart());
  while (a - 1 >= 1 && /^\s*(\/\/|\/\*|\*)/.test(lines[a - 2])) a--;
  return { a, b: lineOf(st.getEnd()), st };
});
const removed = new Set();
chunks.forEach(c => { for (let l = c.a; l <= c.b; l++) removed.add(l); });
const hookBody = chunks.map(c => lines.slice(c.a - 1, c.b).join('\n')).join('\n');

// what the rest of the component uses of the hook's names
const stayingUsed = usedNames(staying);
const returned = [...movedNames].filter(n => stayingUsed.has(n));
const allInputs = [...[...inputsByHook.values()].flat(), ...propInputs];
const typeParts = [...inputsByHook.entries()].map(([h, names]) => `Pick<ReturnType<typeof ${h}>, ${names.map(n => `'${n}'`).join(' | ')}>`);
if (propInputs.length) {
  const withDef = propInputs.filter(n => propHasDefault.has(n)), noDef = propInputs.filter(n => !propHasDefault.has(n));
  if (noDef.length) typeParts.push(`Pick<${propsType}, ${noDef.map(n => `'${n}'`).join(' | ')}>`);
  if (withDef.length) typeParts.push(`Required<Pick<${propsType}, ${withDef.map(n => `'${n}'`).join(' | ')}>>`);
}
const paramText = allInputs.length ? `{ ${allInputs.join(', ')} }: ${typeParts.join(' & ')}` : '';
const hookText = (importLines.length ? importLines.join('\n') + '\n\n' : '') +
  `export function ${hookName}(${paramText}) {\n${hookBody}\n\n${returned.length ? `  return {\n${returned.map(n => '    ' + n + ',').join('\n')}\n  };\n` : ''}}\n`;

// ---- where can the call go? ---------------------------------------------------------
const idx = new Map(body.map((st, i) => [st, i]));
const isEffect = st => ts.isExpressionStatement(st) && ts.isCallExpression(st.expression) && ts.isIdentifier(st.expression.expression) && /^use(Layout|Insertion)?Effect$/.test(st.expression.expression.text);
const declIdx = n => { const st = stayingBodyNames.get(n); return st ? idx.get(st) : -1; };
const minInput = Math.max(-1, ...allInputs.filter(n => stayingBodyNames.has(n)).map(declIdx));
const firstUser = (() => { let m = Infinity; for (const st of staying) { const u = usedNames([st]); if (returned.some(n => u.has(n))) m = Math.min(m, idx.get(st)); } return m; })();
const movedEffects = moved.filter(isEffect).map(st => idx.get(st));
let callAt = null, why = '';
for (const st of moved) {
  const p = idx.get(st);
  if (p <= minInput) { why = `inputs are declared at statement ${minInput}, after ${p}`; continue; }
  if (p >= firstUser) { why = `an output is used before the call position`; continue; }
  const lo = movedEffects.length ? Math.min(p, ...movedEffects) : p, hi = movedEffects.length ? Math.max(p, ...movedEffects) : p;
  const clash = staying.find(x => isEffect(x) && idx.get(x) > lo && idx.get(x) < hi);
  if (movedEffects.length && clash) { why = `would reorder effects (staying effect at line ${lineOf(clash.getStart())})`; continue; }
  callAt = st; break;
}
if (!callAt) { console.log('cannot place the hook call: ' + why); process.exit(1); }

// ---- rewrite the source ---------------------------------------------------------
const callChunk = chunks.find(c => c.st === callAt);
const callLine = `  ${returned.length ? `const { ${returned.join(', ')} } = ` : ''}${hookName}(${allInputs.length ? `{ ${allInputs.join(', ')} }` : ''});`;
const out = [];
lines.forEach((l, i) => {
  const n = i + 1;
  if (n === callChunk.a) out.push(callLine);
  if (!removed.has(n)) out.push(l);
});
let srcAfter = out.join('\n');
// drop imports only this move made unused, add the hook import
const sf2 = ts.createSourceFile(srcPath, srcAfter, ts.ScriptTarget.Latest, true, kind);
const usedAfter = usedNames(sf2.statements.filter(s => !ts.isImportDeclaration(s)));
let rebuilt = srcAfter;
for (const st of sf2.statements.filter(s => ts.isImportDeclaration(s)).reverse()) {
  const c = st.importClause; if (!c) continue;
  const def = c.name && usedAfter.has(c.name.text) ? c.name.text : null;
  let ns = null, named = [];
  if (c.namedBindings) { if (ts.isNamespaceImport(c.namedBindings)) ns = usedAfter.has(c.namedBindings.name.text) ? c.namedBindings.name.text : null; else named = c.namedBindings.elements.filter(e => usedAfter.has(e.name.text)); }
  const total = (c.name ? 1 : 0) + (c.namedBindings ? (ts.isNamespaceImport(c.namedBindings) ? 1 : c.namedBindings.elements.length) : 0);
  const keep = (def ? 1 : 0) + (ns ? 1 : 0) + named.length;
  if (keep === total) continue;
  const droppedByUs = [c.name && !def && usedByMoved.has(c.name.text), ...(c.namedBindings && ts.isNamedImports(c.namedBindings) ? c.namedBindings.elements.filter(e => !usedAfter.has(e.name.text)).map(e => usedByMoved.has(e.name.text)) : [])].some(Boolean);
  if (!droppedByUs) continue;
  const s0 = st.getStart(sf2), e0 = st.getEnd();
  let repl = '';
  if (keep) {
    const parts = [];
    if (def) parts.push(def);
    if (ns) parts.push('* as ' + ns);
    if (named.length) parts.push('{ ' + named.map(e => e.getText(sf2)).join(', ') + ' }');
    repl = `import ${c.isTypeOnly ? 'type ' : ''}${parts.join(', ')} from ${st.moduleSpecifier.getText(sf2)};`;
  }
  rebuilt = rebuilt.slice(0, s0) + repl + rebuilt.slice(e0 + (repl ? 0 : (rebuilt[e0] === '\n' ? 1 : 0)));
}
srcAfter = rebuilt;
{
  const sf3 = ts.createSourceFile(srcPath, srcAfter, ts.ScriptTarget.Latest, true, kind);
  const last = sf3.statements.filter(s => ts.isImportDeclaration(s)).pop();
  const stmt = `import { ${hookName} } from '${rel(srcPath, outPath)}';`;
  const pos = last ? last.getEnd() : 0;
  srcAfter = srcAfter.slice(0, pos) + (last ? '\n' : '') + stmt + (last ? '' : '\n') + srcAfter.slice(pos);
}

console.log(`selected ${moved.length} statements, ~${removed.size} lines -> ${hookName} in ${path.relative(process.cwd(), outPath)}; hook takes ${allInputs.length} input(s), returns ${returned.length} name(s)`);
if (mode === 'plan') { console.log('(plan only; nothing written)'); process.exit(0); }
if (fs.existsSync(outPath)) { console.error(outPath + ' exists'); process.exit(2); }
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, hookText);
fs.writeFileSync(srcPath, srcAfter);
console.log(`ok: wrote ${path.relative(process.cwd(), outPath)} (${hookText.split('\n').length} lines); ${path.basename(srcPath)} now ${srcAfter.split('\n').length} lines`);
