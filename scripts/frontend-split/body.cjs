// Usage: node body.cjs <file.tsx> <FunctionName>  -> statements inside a component body
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const fs = require('fs');
const [file, fname] = process.argv.slice(2);
const src = fs.readFileSync(file, 'utf8');
const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let fn = sf.statements.find(s => ts.isFunctionDeclaration(s) && s.name && s.name.text === fname);
if (!fn) {
  for (const s of sf.statements) if (ts.isVariableStatement(s)) for (const d of s.declarationList.declarations)
    if (d.name.getText() === fname && d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer))) fn = d.initializer;
}
for (const st of fn.body.statements) {
  const a = sf.getLineAndCharacterOfPosition(st.getStart()).line + 1;
  const b = sf.getLineAndCharacterOfPosition(st.getEnd()).line + 1;
  let name = '';
  if (ts.isVariableStatement(st)) name = st.declarationList.declarations.map(d => d.name.getText().slice(0,60)).join(' ');
  else if (ts.isFunctionDeclaration(st)) name = st.name.text;
  else if (ts.isExpressionStatement(st)) name = st.expression.getText().slice(0,50).replace(/\n/g,' ');
  else if (ts.isReturnStatement(st)) name = 'return …';
  console.log(`${String(a).padStart(5)}-${String(b).padEnd(5)} ${String(b-a+1).padStart(4)} ${ts.SyntaxKind[st.kind].replace('Statement','')} ${name}`);
}
