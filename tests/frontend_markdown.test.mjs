import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import { markdownSegments } from '../frontend/src/markdownSegments.js';
import { DIAGRAM_CONFIG, renderDiagram, sanitizeDiagramSvg, validateDiagramSource } from '../frontend/src/diagramRenderer.js';

const frontendRequire = createRequire(new URL('../frontend/package.json', import.meta.url));
const serviceRequire = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
const { JSDOM } = serviceRequire('jsdom');
const { transformSync } = serviceRequire('esbuild');
const React = frontendRequire('react');
const { renderToStaticMarkup } = frontendRequire('react-dom/server');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://127.0.0.1' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.DOMParser = dom.window.DOMParser;
globalThis.CSSStyleSheet = dom.window.CSSStyleSheet;
const purifier = frontendRequire('dompurify')(dom.window);

const componentUrl = new URL('../frontend/src/components/MarkdownRenderer.jsx', import.meta.url);
const compiled = transformSync(readFileSync(componentUrl, 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
const componentModule = { exports: {} };
const componentRequire = createRequire(componentUrl);
new Function('require', 'module', 'exports', compiled)(
  name => name.endsWith('.css') ? undefined : componentRequire(name), componentModule, componentModule.exports,
);
const MarkdownRenderer = componentModule.exports.default;

test('architecture report has headings, numbered steps, table, and a separate completed diagram', () => {
  const content = '## Architecture\n\n| Component | Role |\n| --- | --- |\n| Redis | Session cache |\n\n1. Receive request\n2. Run workers\n\n```mermaid\nflowchart LR\n  Agent["Kratos Agent"] --> Redis["Redis"]\n```\n';
  const html = renderToStaticMarkup(React.createElement(MarkdownRenderer, { content, isStreaming: false }));
  assert.match(html, /<h2[^>]*>Architecture<\/h2>/);
  assert.match(html, /<table[^>]*>/);
  assert.match(html, /<ol[^>]*>/);
  assert.match(html, /aria-label="Architecture diagram"/);
  const diagram = markdownSegments(content).find(segment => segment.lang === 'mermaid');
  assert.equal(diagram.complete, true);
  assert.match(diagram.code, /Kratos Agent/);
});

test('unfinished diagram stays source-only and inline backticks do not end a code fence', () => {
  const [segment] = markdownSegments('```mermaid\nflowchart LR\n  A --> B');
  assert.equal(segment.complete, false);
  const html = renderToStaticMarkup(React.createElement(MarkdownRenderer, { content: '```mermaid\nflowchart LR\n  A --> B', isStreaming: true }));
  assert.match(html, /Diagram is being written/);
  assert.doesNotMatch(html, /<svg/);
  assert.equal(markdownSegments('````text\n``` literal inner fence\n````\n')[0].code, '``` literal inner fence\n');
});

test('plain greeting stays a paragraph and hostile prose/code stays escaped', () => {
  const greeting = renderToStaticMarkup(React.createElement(MarkdownRenderer, { content: 'Hi! How can I help?' }));
  assert.match(greeting, /<p[^>]*>Hi! How can I help\?<\/p>/);
  assert.doesNotMatch(greeting, /<h[1-6]|<table|diagram-panel/);
  const content = '<script>alert(1)</script>\n```html\n<img src=x onerror="alert(2)">\n```\n';
  const html = renderToStaticMarkup(React.createElement(MarkdownRenderer, { content }));
  assert.doesNotMatch(html, /<script>|<img\s/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;img/);
});

test('strict diagrams reject configuration overrides and oversized sources', async () => {
  assert.equal(DIAGRAM_CONFIG.securityLevel, 'strict');
  assert.equal(DIAGRAM_CONFIG.htmlLabels, false);
  for (const code of [
    '%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\n A --> B',
    '---\nconfig:\n  securityLevel: loose\n---\nflowchart LR\n A --> B',
    'x'.repeat(DIAGRAM_CONFIG.maxTextSize + 1),
  ]) {
    assert.throws(() => validateDiagramSource(code), /diagram_source_unavailable/);
  }
  let rendered = false;
  await assert.rejects(renderDiagram('broken diagram', 'test-invalid', {
    purifier,
    engine: { parse: async () => false, render: async () => { rendered = true; } },
  }), /diagram_syntax_unavailable/);
  assert.equal(rendered, false);
});

test('SVG sanitizer removes event handlers, scripts, links, foreign HTML, and remote images', () => {
  const dirty = '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script><foreignObject><img src="x" onerror="alert(3)"/></foreignObject><a href="javascript:alert(4)"><text>link</text></a><image href="https://example.com/track"/><rect width="100" height="20"/><text>Kratos</text></svg>';
  const clean = sanitizeDiagramSvg(dirty, purifier);
  assert.doesNotMatch(clean, /onload|onerror|script|foreignObject|<a\b|href|<image\b/i);
  assert.match(clean, /<rect/);
  assert.match(clean, /Kratos/);
  assert.throws(() => sanitizeDiagramSvg('<svg xmlns="http://www.w3.org/2000/svg"><style>.node{fill:url(https://example.com/track)}</style></svg>', purifier), /diagram_external_resource/);
});

test('rendering sanitizes the returned SVG without binding click handlers', async () => {
  let bound = false;
  const svg = await renderDiagram('flowchart LR\n A --> B', 'test-safe', {
    purifier,
    engine: {
      parse: async () => ({ diagramType: 'flowchart-v2' }),
      render: async () => ({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text onclick="alert(1)">Agent</text></svg>', bindFunctions: () => { bound = true; } }),
    },
  });
  assert.match(svg, /Agent/);
  assert.doesNotMatch(svg, /onclick/);
  assert.equal(bound, false);
});

test('installed Mermaid renders an architecture flowchart through the production sanitizer', async () => {
  // jsdom supplies a DOM but no SVG layout; deterministic geometry makes the
  // real Mermaid pipeline testable without using a user's browser session.
  dom.window.SVGElement.prototype.getBBox = function () {
    return { x: 0, y: 0, width: Math.max(40, (this.textContent || '').length * 8), height: 20 };
  };
  dom.window.SVGElement.prototype.getComputedTextLength = function () { return (this.textContent || '').length * 8; };
  const svg = await renderDiagram('flowchart LR\n Agent["Kratos Agent"] --> Cache["Redis"]', 'kratos-test-real');
  assert.match(svg, /<svg\s/);
  const labels = new dom.window.DOMParser().parseFromString(svg, 'image/svg+xml').querySelectorAll('text');
  const text = [...labels].map(label => label.textContent).join(' ');
  assert.match(text, /Kratos/);
  assert.match(text, /Agent/);
  assert.match(text, /Redis/);
  assert.doesNotMatch(svg, /foreignObject|<script|onload=|onclick=/i);
});

test('invalid diagram falls back to escaped source in the mounted chat component', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = frontendRequire('react-dom/client');
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  try {
    await React.act(async () => {
      root.render(React.createElement(MarkdownRenderer, {
        content: '```mermaid\n<script>alert(1)</script>\n```\n', isStreaming: false,
      }));
    });
    await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    assert.match(container.textContent, /Diagram preview is unavailable/);
    assert.match(container.querySelector('code').textContent, /<script>alert\(1\)<\/script>/);
    assert.equal(container.querySelector('script'), null);
    assert.equal(container.querySelector('svg'), null);
  } finally {
    await React.act(async () => { root.unmount(); });
    container.remove();
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  }
});
