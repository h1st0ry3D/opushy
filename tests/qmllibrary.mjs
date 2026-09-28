// Loads a QML .js library into a plain JS context, so the same file the panel
// imports can be exercised by `node --test` without a QML runtime.
//
// A QML .js library is a script, not a module: no `export`, and its top-level
// functions and vars become the library's properties. Evaluating it in a fresh
// context and reading the globals back gives that shape. `.pragma library` is a
// QML directive, so it is stripped before the evaluation.
import { readFileSync } from "node:fs";
import vm from "node:vm";

export function loadLibrary(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), "utf8");
  const context = vm.createContext({ Math, Date, JSON, Number, String, Array, isFinite, isNaN, parseInt, parseFloat, RegExp, console });
  vm.runInContext(source.replace(/^\s*\.pragma library\s*$/m, ""), context, { filename: relativePath });
  return context;
}

// Values built inside the vm context carry that realm's prototypes, so
// deepStrictEqual against a literal from this realm needs a plain copy first.
export function plain(value) {
  return JSON.parse(JSON.stringify(value));
}
