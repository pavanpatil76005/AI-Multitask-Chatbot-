import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import React from "react";
import * as jsx from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const source = ts.transpileModule(fs.readFileSync("src/components/Markdown.tsx", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exports = {};
vm.runInNewContext(source, { exports, require: name => ({
  "react/jsx-runtime": jsx, "react-markdown": { default: ReactMarkdown }, "remark-gfm": { default: remarkGfm },
})[name] });
const render = content => renderToStaticMarkup(React.createElement(exports.default, null, content));

test("assistant Markdown renders headings, bold, separators, lists and GFM tables", () => {
  const html = render("### Energy\n\n**nuclear fusion**\n\n---\n\n- Hydrogen\n- Helium\n\n|A|B|\n|-|-|\n|1|2|");
  for (const expected of ["<h3>Energy</h3>", "<strong>nuclear fusion</strong>", "<hr/>", "<ul>", "<table>", "<td>2</td>"]) {
    assert.ok(html.includes(expected), expected);
  }
});

test("generated HTML, unsafe URLs, and remote images cannot execute or track", () => {
  const html = render('<script>alert(1)</script>\n\n[bad](javascript:alert)\n\n![tracking](https://example.com/pixel.png)');
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("javascript:"));
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("[Image: tracking]"));
});

test("code blocks preserve source text and links have safe new-tab attributes", () => {
  const html = render('```python\nprint("hello")\n```\n\n[Documentation](https://example.com)');
  assert.ok(html.includes('class="language-python"'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
  assert.ok(html.includes('target="_blank"'));
});
