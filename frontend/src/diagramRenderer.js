export const DIAGRAM_CONFIG = Object.freeze({
  startOnLoad: false,
  securityLevel: 'strict',
  htmlLabels: false,
  theme: 'dark',
  fontFamily: 'Inter, Arial, sans-serif',
  suppressErrorRendering: true,
  maxTextSize: 20000,
  maxEdges: 200,
  flowchart: { htmlLabels: false, useMaxWidth: true },
  secure: [
    'secure', 'securityLevel', 'startOnLoad', 'htmlLabels', 'themeCSS',
    'suppressErrorRendering', 'maxTextSize', 'maxEdges',
  ],
});

let dependencies;
async function loadDependencies() {
  dependencies ??= Promise.all([import('mermaid'), import('dompurify')]).then(([diagram, sanitizer]) => {
    diagram.default.initialize(DIAGRAM_CONFIG);
    return { engine: diagram.default, purifier: sanitizer.default };
  });
  return dependencies;
}

export function validateDiagramSource(value) {
  const source = String(value ?? '').trim();
  if (!source || source.length > DIAGRAM_CONFIG.maxTextSize ||
    source.includes('%%{') || /^---(?:\r?\n|$)/.test(source)) {
    throw new Error('diagram_source_unavailable');
  }
  return source;
}

export function sanitizeDiagramSvg(value, purifier) {
  const svg = purifier.sanitize(String(value ?? ''), {
    USE_PROFILES: { svg: true, svgFilters: true },
    FORBID_TAGS: ['script', 'iframe', 'foreignObject', 'image', 'a', 'animate', 'animateMotion', 'animateTransform', 'set'],
    FORBID_ATTR: ['href', 'xlink:href', 'src', 'xml:base'],
    KEEP_CONTENT: false,
  });
  if (!/^\s*<svg(?:\s|>)/i.test(svg) || /@import|javascript\s*:/i.test(svg)) {
    throw new Error('diagram_svg_unavailable');
  }
  for (const reference of svg.matchAll(/url\s*\(\s*(['"]?)(.*?)\1\s*\)/gi)) {
    if (!/^#[\w.:-]+$/.test(reference[2].trim())) {
      throw new Error('diagram_external_resource');
    }
  }
  return svg;
}

export async function renderDiagram(source, id, overrides) {
  const code = validateDiagramSource(source);
  const { engine, purifier } = overrides || await loadDependencies();
  // Validate before rendering so malformed streaming output cannot leave an
  // error graphic in the document. Interactions are deliberately not bound.
  if (!await engine.parse(code, { suppressErrors: true })) throw new Error('diagram_syntax_unavailable');
  const { svg } = await engine.render(id, code);
  return sanitizeDiagramSvg(svg, purifier);
}
