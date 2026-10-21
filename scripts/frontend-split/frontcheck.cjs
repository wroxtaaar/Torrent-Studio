// Offline sanity check for the frontend (no node_modules available in the authoring sandbox).
// Reports only diagnostics that prove a broken split: unknown names (2304), missing exports
// of *local* modules (2305), unresolved local imports (2307 with a relative path) and syntax errors.
// Usage: node frontcheck.cjs [frontendDir]   (default: ../../frontend)
const ts = require('/home/claude/.npm-global/lib/node_modules/typescript');
const path = require('path');
const fs = require('fs');
const root = path.resolve(process.argv[2] || path.join(__dirname, '../../frontend'));
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (e.name === 'node_modules') continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (/\.(ts|tsx)$/.test(e.name) && !e.name.endsWith('.d.ts')) files.push(p);
  }
})(path.join(root, 'src'));
const program = ts.createProgram(files, {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  jsx: ts.JsxEmit.ReactJSX, allowImportingTsExtensions: true, resolveJsonModule: true, noEmit: true,
  skipLibCheck: true, types: [], lib: ['lib.es2022.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'], isolatedModules: true,
  allowJs: true, esModuleInterop: true, allowSyntheticDefaultImports: true,
});
let bad = 0;
const interesting = new Set([2304, 2305, 2552, 2551, 2451, 2300]);
for (const sf of program.getSourceFiles()) {
  if (sf.isDeclarationFile || sf.fileName.includes('node_modules')) continue;
  const diags = [...program.getSyntacticDiagnostics(sf), ...program.getSemanticDiagnostics(sf)];
  for (const d of diags) {
    const msg = ts.flattenDiagnosticMessageText(d.messageText, '\n');
    const keep = d.category === ts.DiagnosticCategory.Error && (
      d.code < 2000 || interesting.has(d.code) ||
      (d.code === 2307 && /'\.{1,2}\//.test(msg)) || d.code === 2614 || d.code === 2724);
    if (!keep) continue;
    // `React.FC` & friends come from @types/react which is not installed here.
    if (d.code === 2304 && /Cannot find name '(React|JSX)'/.test(msg)) continue;
    const { line } = sf.getLineAndCharacterOfPosition(d.start || 0);
    console.log(`${path.relative(root, sf.fileName)}:${line + 1}  TS${d.code} ${msg.split('\n')[0]}`);
    bad++;
  }
}
console.log(bad ? `${bad} problem(s)` : `ok: ${files.length} files, no unknown names / broken local imports`);
process.exit(bad ? 1 : 0);
