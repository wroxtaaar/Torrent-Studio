// Move statements from the BODY of a React component into a custom hook in a new module.
//
//   node extract-hook.cjs plan|apply <src-file> <Component> <hookName> <new-module> <A-B[,C-D...]> [--allow-effect-reorder]
//
// Types are never written by hand: the hook takes ONE context object whose type is built from
//   * ReturnType<typeof useOther>     for values that come from hooks extracted earlier (the tool finds
//                                     them by looking for `const {...} = useOther(...)` in the component),
//   * the component's props type      for props.
// Everything the moved code reads from the component that is NOT available that way (e.g. a raw
// `useState` still living in the component) is reported as a blocker: extract that first, in a
// state hook, then this one. The hook returns every name the remaining component code still uses.
//
// Safety: it checks that the hook call can sit before the first consumer and after the last producer,
// and (unless --allow-effect-reorder) that the relative order of effects is unchanged.
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2).filter(a => !a.startsWith('--'));
const flags = new Set(process.argv.slice(2).filter(a => a.startsWith('--')));
const [mode, srcArg, componentName, hookName, modArg, rangesArg] = args;
if (!['plan', 'apply'].includes(mode) || !rangesArg) {
  console.error('usage: extract-hook.cjs plan|apply <src> <Component> <hookName> <new-module> <A-B,...> [--allow-effect-reorder]');
  process.exit(2);
}
const srcPath = path.resolve(srcArg), modPath = path.resolve(modArg);
const ranges = rangesArg.split(',').map(r => r.split('-').map(Number));
const inRange = l => ranges.some(([a, b]) => l >= a && l <= b);
const text = fs.readFileSync(srcPath, 'utf8');
const lines = text.split('\n');
const kind = srcPath.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
const sf = ts.createSourceFile(srcPath, text, ts.ScriptTarget.Latest, true, kind);
const lineOf = n => sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
const endLineOf = n => sf.getLineAndCharacterOfPosition(n.getEnd()).line + 1;

const bindNames = (n, out) => {
  if (ts.isIdentifier(n)) out.push(n.text);
  else if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) n.elements.forEach(e => { if (!ts.isOmittedExpression(e)) bindNames(e.name, out); });
};
function declared(st) {
  const out = [];
  if (ts.isFunctionDeclaration(st) || ts.isTypeAliasDeclaration(st)) { if (st.name) out.push(st.name.text); }
  else if (ts.isVariableStatement(st)) st.declarationList.declarations.forEach(d => bindNames(d.name, out));
  return out;
}
// Free (not locally declared) identifier names used by the given nodes. Scope aware so that a
// `catch (error)` or a local `const query` does not count as a use of a component-level `error`/`query`.
function usedNames(nodes) {
  const free = new Set();
  const isRef = n => {
    const p = n.parent;
    return !(p && ((ts.isPropertyAccessExpression(p) && p.name === n) || (ts.isQualifiedName(p) && p.right === n) ||
      (ts.isPropertyAssignment(p) && p.name === n) || (ts.isPropertySignature(p) && p.name === n) ||
      (ts.isJsxAttribute(p) && p.name === n) || (ts.isMethodDeclaration(p) && p.name === n) ||
      (ts.isBindingElement(p) && p.propertyName === n)));
  };
  const collect = (node, set) => {   // names declared directly by this scope node
    const addBind = b => { const o = []; bindNames(b, o); o.forEach(x => set.add(x)); };
    const fromStatements = sts => sts.forEach(st => {
      if (ts.isVariableStatement(st)) st.declarationList.declarations.forEach(d => addBind(d.name));
      else if ((ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st) || ts.isTypeAliasDeclaration(st) || ts.isInterfaceDeclaration(st)) && st.name) set.add(st.name.text);
    });
    if (ts.isBlock(node) || ts.isSourceFile(node) || ts.isModuleBlock(node)) fromStatements(node.statements);
    else if (ts.isCaseBlock(node)) node.clauses.forEach(c => fromStatements(c.statements));
    else if (ts.isCatchClause(node) && node.variableDeclaration) addBind(node.variableDeclaration.name);
    else if ((ts.isForStatement(node) || ts.isForInStatement(node) || ts.isForOfStatement(node)) && node.initializer && ts.isVariableDeclarationList(node.initializer)) node.initializer.declarations.forEach(d => addBind(d.name));
    else if (ts.isFunctionLike(node)) {
      node.parameters.forEach(pm => addBind(pm.name));
      if (ts.isFunctionExpression(node) && node.name) set.add(node.name.text);
      if (node.typeParameters) node.typeParameters.forEach(tp => set.add(tp.name.text));
      // `var` / function declarations anywhere inside are hoisted to this function scope: Block handles let/const/function.
    }
  };
  const walk = (n, stack) => {
    let scope = stack;
    if (ts.isBlock(n) || ts.isCaseBlock(n) || ts.isCatchClause(n) || ts.isForStatement(n) || ts.isForInStatement(n) || ts.isForOfStatement(n) || ts.isFunctionLike(n)) {
      const set = new Set(); collect(n, set); scope = [...stack, set];
    }
    if (ts.isIdentifier(n) && isRef(n)) {
      if (!scope.some(set => set.has(n.text))) free.add(n.text);
    }
    ts.forEachChild(n, c => walk(c, scope));
  };
  (Array.isArray(nodes) ? nodes : [nodes]).forEach(n => walk(n, []));
  return free;
}

// ---- find the component ---------------------------------------------------------------------
let fn = null, propsTypeName = null;
for (const s of sf.statements) {
  if (ts.isFunctionDeclaration(s) && s.name && s.name.text === componentName) fn = s;
  if (ts.isVariableStatement(s)) for (const d of s.declarationList.declarations)
    if (d.name.getText() === componentName && d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer))) {
      fn = d.initializer;
      // React.FC<Props>
      if (d.type && ts.isTypeReferenceNode(d.type) && d.type.typeArguments && d.type.typeArguments[0]) propsTypeName = d.type.typeArguments[0].getText();
    }
}
if (!fn) { console.error('component not found'); process.exit(2); }
if (!propsTypeName && fn.parameters[0] && fn.parameters[0].type) propsTypeName = fn.parameters[0].type.getText();
const stmts = [...fn.body.statements];

// props: destructured names (with / without default)
const propNames = new Map(); // name -> {hasDefault}
const propParam = fn.parameters[0];
if (propParam && ts.isObjectBindingPattern(propParam.name)) {
  for (const e of propParam.name.elements) propNames.set(e.name.getText(), { hasDefault: !!e.initializer, key: (e.propertyName || e.name).getText() });
}

// ---- hooks already extracted (registry by scanning the component) ------------------------------
const importedLocal = new Map(); // name -> spec for relative imports
for (const st of sf.statements) if (ts.isImportDeclaration(st) && st.moduleSpecifier.text.startsWith('.')) {
  const c = st.importClause;
  if (c && c.namedBindings && ts.isNamedImports(c.namedBindings)) c.namedBindings.elements.forEach(e => importedLocal.set(e.name.text, st.moduleSpecifier.text));
}
const hookOf = new Map(); // declared name -> hook function name
const moved = [], staying = [];
stmts.forEach((st, i) => (inRange(lineOf(st)) ? moved : staying).push({ st, i }));
if (!moved.length) { console.error('nothing selected'); process.exit(2); }
for (const { st } of staying) {
  if (!ts.isVariableStatement(st)) continue;
  for (const d of st.declarationList.declarations) {
    if (d.initializer && ts.isCallExpression(d.initializer) && ts.isIdentifier(d.initializer.expression) &&
        importedLocal.has(d.initializer.expression.text) && /^use[A-Z]/.test(d.initializer.expression.text)) {
      const out = []; bindNames(d.name, out);
      out.forEach(n => hookOf.set(n, d.initializer.expression.text));
    }
  }
}
const stayingDeclaredBy = new Map(); // name -> index
staying.forEach(({ st, i }) => declared(st).forEach(n => stayingDeclaredBy.set(n, i)));
const movedDeclared = new Set(moved.flatMap(({ st }) => declared(st)));

// ---- inputs ---------------------------------------------------------------------------------
const usedByMoved = usedNames(moved.map(m => m.st));
const inputsFromHooks = new Map(); // hookFn -> Set(names)
const inputsFromProps = [];
const blockers = [];
let lastProducer = -1;
for (const name of usedByMoved) {
  if (movedDeclared.has(name)) continue;
  if (stayingDeclaredBy.has(name)) {
    const idx = stayingDeclaredBy.get(name);
    lastProducer = Math.max(lastProducer, idx);
    if (hookOf.has(name)) {
      const h = hookOf.get(name);
      if (!inputsFromHooks.has(h)) inputsFromHooks.set(h, new Set());
      inputsFromHooks.get(h).add(name);
    } else blockers.push(`${name} (line ${lineOf(stmts[idx])}) is declared in the component outside a hook; extract it first`);
  } else if (propNames.has(name)) inputsFromProps.push(name);
}
if (blockers.length) { console.log('cannot move yet:\n  - ' + blockers.join('\n  - ')); process.exit(1); }

// ---- outputs / placement ----------------------------------------------------------------------
const stayingNodes = staying.map(s => s.st);
const retNode = null;
const usedByStaying = usedNames(stayingNodes);
const outputs = [...movedDeclared].filter(n => usedByStaying.has(n));
const firstMoved = moved[0].i;
let firstConsumer = stmts.length;
for (const { st, i } of staying) {
  const u = usedNames(st);
  if (outputs.some(o => u.has(o))) { firstConsumer = Math.min(firstConsumer, i); }
}
const callIndex = Math.max(firstMoved, lastProducer + 1); // hook call goes right before statement index `callIndex`
if (callIndex > firstConsumer) {
  console.log(`cannot place the hook call: it must come after statement at line ${lineOf(stmts[lastProducer])} (it provides an input) but before line ${lineOf(stmts[firstConsumer])} (it uses an output)`);
  process.exit(1);
}
// effect order
const isEffect = st => ts.isExpressionStatement(st) && /^use(Layout)?Effect\b/.test(st.expression.getText());
const reorder = [];
for (const m of moved.filter(m => isEffect(m.st)))
  for (const s of staying.filter(s => isEffect(s.st))) {
    const origBefore = m.i < s.i, newBefore = callIndex <= s.i;
    if (origBefore !== newBefore) reorder.push(`effect at line ${lineOf(m.st)} would now run ${newBefore ? 'before' : 'after'} the effect at line ${lineOf(s.st)}`);
  }
if (reorder.length && !flags.has('--allow-effect-reorder')) {
  console.log('effect order would change (use --allow-effect-reorder if they are independent):\n  - ' + reorder.slice(0, 8).join('\n  - ') + (reorder.length > 8 ? `\n  ... ${reorder.length - 8} more` : ''));
  process.exit(1);
}

// ---- hook module ------------------------------------------------------------------------------
const relFrom = (from, to) => { let r = path.relative(path.dirname(from), to).split(path.sep).join('/'); return r.startsWith('.') ? r : './' + r; };
const rewriteSpec = (spec, fromSrc, toNew) => spec.startsWith('.') ? relFrom(toNew, path.resolve(path.dirname(fromSrc), spec)) : spec;
const importsInfo = [];
for (const st of sf.statements) if (ts.isImportDeclaration(st)) {
  const c = st.importClause;
  const rec = { st, spec: st.moduleSpecifier.text, typeOnly: !!(c && c.isTypeOnly), def: c && c.name ? c.name.text : null, ns: null, named: [] };
  if (c && c.namedBindings) {
    if (ts.isNamespaceImport(c.namedBindings)) rec.ns = c.namedBindings.name.text;
    else c.namedBindings.elements.forEach(e => rec.named.push({ name: (e.propertyName || e.name).text, local: e.name.text, typeOnly: e.isTypeOnly }));
  }
  importsInfo.push(rec);
}
const hookBodyUses = usedByMoved;
const modImports = [];
for (const imp of importsInfo) {
  if (!imp.def && !imp.ns && !imp.named.length) continue;
  const named = imp.named.filter(n => hookBodyUses.has(n.local));
  const def = imp.def && hookBodyUses.has(imp.def) ? imp.def : null;
  const ns = imp.ns && hookBodyUses.has(imp.ns) ? imp.ns : null;
  if (!named.length && !def && !ns) continue;
  const parts = [];
  if (def) parts.push(def);
  if (ns) parts.push(`* as ${ns}`);
  if (named.length) parts.push('{ ' + named.map(n => (n.typeOnly ? 'type ' : '') + (n.name === n.local ? n.name : `${n.name} as ${n.local}`)).join(', ') + ' }');
  modImports.push(`import ${imp.typeOnly ? 'type ' : ''}${parts.join(', ')} from '${rewriteSpec(imp.spec, srcPath, modPath)}';`);
}
// top-level declarations of the component file that moved code uses (types/consts) -> would be circular
const topDeclared = new Set(sf.statements.filter(s => !ts.isImportDeclaration(s)).flatMap(s => {
  if (s === fn || (ts.isVariableStatement(s) && s.declarationList.declarations.some(d => d.initializer === fn))) return [];
  return declared(s).concat(ts.isInterfaceDeclaration(s) ? [s.name.text] : []);
}));
const topUses = [...hookBodyUses].filter(n => topDeclared.has(n) && !movedDeclared.has(n));
if (topUses.length) {
  console.log('cannot move yet: the moved code uses top-level declarations of ' + path.basename(srcPath) + ' (' + topUses.join(', ') + '); move them to a module first');
  process.exit(1);
}
const ctxParts = [];
for (const [h, names] of inputsFromHooks) {
  modImports.push(`import { ${h} } from '${rewriteSpec(importedLocal.get(h), srcPath, modPath)}';`);
  ctxParts.push(`Pick<ReturnType<typeof ${h}>, ${[...names].sort().map(n => `'${n}'`).join(' | ')}>`);
}
const propsSorted = [...new Set(inputsFromProps)].sort();
const withDef = propsSorted.filter(n => propNames.get(n).hasDefault), noDef = propsSorted.filter(n => !propNames.get(n).hasDefault);
let needsPropsImport = false;
if (propsSorted.length) {
  if (!propsTypeName) { console.log('cannot determine the props type of ' + componentName); process.exit(1); }
  needsPropsImport = true;
  if (noDef.length) ctxParts.push(`Pick<${propsTypeName}, ${noDef.map(n => `'${propNames.get(n).key}'`).join(' | ')}>`);
  if (withDef.length) ctxParts.push(`Required<Pick<${propsTypeName}, ${withDef.map(n => `'${propNames.get(n).key}'`).join(' | ')}>>`);
}
if (needsPropsImport) {
  const compSpecNoExt = relFrom(modPath, srcPath);
  modImports.push(`import type { ${propsTypeName} } from '${compSpecNoExt}';`);
}
const ctxNames = [...[...inputsFromHooks.values()].flatMap(s => [...s]), ...propsSorted];
const ctxTypeName = hookName.replace(/^use/, '') + 'Context';
const chunks = moved.map(({ st }) => {
  let a = lineOf(st);
  const leading = ts.getLeadingCommentRanges(text, st.getFullStart()) || [];
  if (leading.length) a = Math.min(a, sf.getLineAndCharacterOfPosition(leading[0].pos).line + 1);
  return { a, b: endLineOf(st), st };
});
// keep chunk starts out of the previous chunk
for (let i = 1; i < chunks.length; i++) chunks[i].a = Math.max(chunks[i].a, chunks[i - 1].b + 1);
let body = '';
chunks.forEach((c, i) => {
  const prev = i ? chunks[i - 1].b : null;
  const gap = prev !== null ? lines.slice(prev, c.a - 1) : [];
  // keep blank separator lines that were *between* moved statements only when they were adjacent in the source
  body += (i ? (gap.every(l => !l.trim()) ? '\n' : '') : '') + lines.slice(c.a - 1, c.b).join('\n') + '\n';
});
const ctxType = ctxParts.length ? ctxParts.join(' & ') : '{}';
const outStr = outputs.length ? `  return { ${outputs.join(', ')} };\n` : '';
const hookSrc =
  (modImports.length ? modImports.join('\n') + '\n\n' : '') +
  (ctxNames.length ? `export type ${ctxTypeName} = ${ctxType};\n\n` : '') +
  `export function ${hookName}(${ctxNames.length ? `{ ${ctxNames.join(', ')} }: ${ctxTypeName}` : ''}) {\n${body.replace(/\n+$/, '\n')}\n${outStr}}\n`;

// ---- edit the component -------------------------------------------------------------------------
const removed = new Set();
chunks.forEach(c => { for (let l = c.a; l <= c.b; l++) removed.add(l); });
const callStmt = `  ${outputs.length ? `const { ${outputs.join(', ')} } = ` : ''}${hookName}(${ctxNames.length ? `{ ${ctxNames.join(', ')} }` : ''});`;
// insertion line: before statement callIndex (or before the first moved chunk when callIndex is a moved statement)
let insertBeforeLine;
const target = stmts[callIndex];
if (!target) insertBeforeLine = endLineOf(stmts[stmts.length - 1]) + 1;
else {
  const m = chunks.find(c => c.st === target);
  if (m) insertBeforeLine = m.a;
  else {
    const leading = ts.getLeadingCommentRanges(text, target.getFullStart()) || [];
    insertBeforeLine = leading.length ? sf.getLineAndCharacterOfPosition(leading[0].pos).line + 1 : lineOf(target);
  }
}
const out = [];
lines.forEach((l, idx) => {
  const ln = idx + 1;
  if (ln === insertBeforeLine) out.push(callStmt);
  if (!removed.has(ln)) out.push(l);
});
let srcAfter = out.join('\n');
// collapse blank-line runs
srcAfter = srcAfter.replace(/\n{3,}/g, '\n\n');

// imports: add hook import, drop imports that became unused because of the move
const sfAfter = ts.createSourceFile(srcPath, srcAfter, ts.ScriptTarget.Latest, true, kind);
const stillUsed = usedNames(sfAfter.statements.filter(s => !ts.isImportDeclaration(s)));
let rebuilt = srcAfter;
for (const st of sfAfter.statements.filter(s => ts.isImportDeclaration(s)).reverse()) {
  const c = st.importClause; if (!c) continue;
  const def = c.name && stillUsed.has(c.name.text) ? c.name.text : null;
  let ns = null, named = [];
  if (c.namedBindings) {
    if (ts.isNamespaceImport(c.namedBindings)) ns = stillUsed.has(c.namedBindings.name.text) ? c.namedBindings.name.text : null;
    else named = c.namedBindings.elements.filter(e => stillUsed.has(e.name.text));
  }
  const total = (c.name ? 1 : 0) + (c.namedBindings ? (ts.isNamespaceImport(c.namedBindings) ? 1 : c.namedBindings.elements.length) : 0);
  const keep = (def ? 1 : 0) + (ns ? 1 : 0) + named.length;
  if (keep === total) continue;
  const droppedByMove = [
    c.name && !def && hookBodyUses.has(c.name.text),
    ...(c.namedBindings && !ts.isNamespaceImport(c.namedBindings) ? c.namedBindings.elements.filter(e => !stillUsed.has(e.name.text)).map(e => hookBodyUses.has(e.name.text)) : []),
  ].some(Boolean);
  if (!droppedByMove) continue;
  const start = st.getStart(sfAfter), end = st.getEnd();
  let repl = '';
  if (keep) {
    const parts = [];
    if (def) parts.push(def);
    if (ns) parts.push(`* as ${ns}`);
    if (named.length) parts.push('{ ' + named.map(e => e.getText(sfAfter)).join(', ') + ' }');
    repl = `import ${c.isTypeOnly ? 'type ' : ''}${parts.join(', ')} from ${st.moduleSpecifier.getText(sfAfter)};`;
  }
  rebuilt = rebuilt.slice(0, start) + repl + rebuilt.slice(end + (repl ? 0 : (rebuilt[end] === '\n' ? 1 : 0)));
}
srcAfter = rebuilt;
{
  const sf2 = ts.createSourceFile(srcPath, srcAfter, ts.ScriptTarget.Latest, true, kind);
  const last = sf2.statements.filter(s => ts.isImportDeclaration(s)).pop();
  const stmt = `import { ${hookName} } from '${relFrom(srcPath, modPath)}';`;
  const pos = last ? last.getEnd() : 0;
  srcAfter = srcAfter.slice(0, pos) + (last ? '\n' : '') + stmt + (last ? '' : '\n') + srcAfter.slice(pos);
}
// props type must be importable from the hook module
if (needsPropsImport && !/export\s+(interface|type)\s+/.test(srcAfter.split('\n').filter(l => l.includes(propsTypeName)).join('\n'))) {
  srcAfter = srcAfter.replace(new RegExp(`^(interface|type) ${propsTypeName}\\b`, 'm'), `export $1 ${propsTypeName}`);
}

console.log(`selected ${moved.length} statements, ~${removed.size} lines -> ${hookName} in ${path.relative(process.cwd(), modPath)}`);
console.log(`inputs: ${ctxNames.join(', ') || '(none)'}`);
console.log(`outputs: ${outputs.length} name(s)`);
if (reorder.length) console.log(`WARNING: effect order changed (allowed): ${reorder.length} pair(s)`);
if (mode === 'plan') { console.log('(plan only; nothing written)'); process.exit(0); }
if (fs.existsSync(modPath)) { console.error(modPath + ' exists; pick another name or append manually'); process.exit(2); }
fs.mkdirSync(path.dirname(modPath), { recursive: true });
fs.writeFileSync(modPath, hookSrc);
fs.writeFileSync(srcPath, srcAfter);
console.log(`ok: wrote ${path.relative(process.cwd(), modPath)} (${hookSrc.split('\n').length} lines); ${path.basename(srcPath)} now ${srcAfter.split('\n').length} lines`);
