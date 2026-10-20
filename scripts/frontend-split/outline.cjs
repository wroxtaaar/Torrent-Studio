// Usage: node outline.cjs <file.tsx>
// Lists top-level statements with line ranges and size, to plan splitting big React files.
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const file = process.argv[2];
const src = fs.readFileSync(file, 'utf8');
const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
for (const st of sf.statements) {
  const a = sf.getLineAndCharacterOfPosition(st.getStart()).line + 1;
  const b = sf.getLineAndCharacterOfPosition(st.getEnd()).line + 1;
  let name = '';
  if (ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st) || ts.isInterfaceDeclaration(st) || ts.isTypeAliasDeclaration(st)) name = st.name ? st.name.text : '(anon)';
  else if (ts.isVariableStatement(st)) name = st.declarationList.declarations.map(d => d.name.getText()).join(',');
  else if (ts.isImportDeclaration(st)) name = 'import ' + st.moduleSpecifier.getText();
  else if (ts.isExportDeclaration(st) || ts.isExportAssignment(st)) name = 'export…';
  const exp = (ts.getCombinedModifierFlags(st) & ts.ModifierFlags.Export) ? 'export ' : '';
  console.log(`${String(a).padStart(5)}-${String(b).padEnd(5)} ${String(b-a+1).padStart(5)}  ${ts.SyntaxKind[st.kind].replace('Declaration','').replace('Statement','')} ${exp}${name}`);
}
