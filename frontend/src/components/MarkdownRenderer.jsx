import React, { useEffect, useId, useState } from 'react';
import { markdownSegments } from '../markdownSegments';
import { renderDiagram } from '../diagramRenderer';
import '../diagrams.css';

// Common language alias mapping from src/kratos_agent/web
const ALIAS_MAP = {
  'js': 'javascript',
  'ts': 'typescript',
  'py': 'python',
  'rs': 'rust',
  'rb': 'ruby',
  'sh': 'bash',
  'shell': 'bash',
  'yml': 'yaml',
  'cs': 'csharp',
  'c++': 'cpp',
  'golang': 'go'
};

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function highlightCode(codeText, lang) {
  let cleanLang = (lang || '').trim().toLowerCase();
  if (ALIAS_MAP[cleanLang]) {
    cleanLang = ALIAS_MAP[cleanLang];
  }

  let highlighted = '';
  let displayLang = cleanLang ? cleanLang.toUpperCase() : 'CODE';

  const hljs = typeof window !== 'undefined' ? window.hljs : null;

  if (hljs) {
    try {
      if (cleanLang && hljs.getLanguage(cleanLang)) {
        highlighted = hljs.highlight(codeText, { language: cleanLang, ignoreIllegals: true }).value;
      } else {
        const autoRes = hljs.highlightAuto(codeText);
        highlighted = autoRes.value;
        if (!cleanLang && autoRes.language) {
          displayLang = autoRes.language.toUpperCase();
        }
      }
    } catch {
      highlighted = escapeHtml(codeText);
    }
  } else {
    highlighted = escapeHtml(codeText);
  }

  const langClass = cleanLang ? `language-${escapeHtml(cleanLang.toLowerCase())}` : '';
  return { highlighted, displayLang, langClass };
}

export function CodeDialogBox({ code, language }) {
  const [copied, setCopied] = useState(false);

  const { highlighted, displayLang, langClass } = highlightCode(code, language);

  const handleCopy = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(code).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }).catch(() => {
        setCopied(false);
      });
    }
  };

  return (
    <div className="code-dialog-box">
      <div className="code-dialog-header">
        <span className="code-lang-badge font-pixl">
          {displayLang}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="btn-copy-code font-pixl"
          style={copied ? { color: '#00ff9d', borderColor: '#00ff9d' } : undefined}
          title="Copy code to clipboard"
        >
          {copied ? 'COPIED!' : 'COPY'}
        </button>
      </div>
      <pre className="scrollbar-thin">
        <code
          className={`hljs ${langClass}`}
          dangerouslySetInnerHTML={{ __html: highlighted }}
        />
      </pre>
    </div>
  );
}

function MermaidDiagram({ code, complete }) {
  const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const [result, setResult] = useState({ svg: '', status: 'waiting', code: '' });
  useEffect(() => {
    if (!complete) return;
    let active = true;
    renderDiagram(code, `kratos-diagram-${instanceId}`)
      .then(svg => { if (active) setResult({ svg, status: 'ready', code }); })
      .catch(() => { if (active) setResult({ svg: '', status: 'fallback', code }); });
    return () => { active = false; };
  }, [code, complete, instanceId]);

  const current = result.code === code ? result : { svg: '', status: 'waiting' };
  return (
    <section className="diagram-panel" aria-label="Architecture diagram">
      {current.svg ? (
        <div className="diagram-svg" role="img" aria-label="Generated diagram"
          dangerouslySetInnerHTML={{ __html: current.svg }} />
      ) : (
        <p className="diagram-status" role="status">
          {!complete ? 'Diagram is being written…' : current.status === 'fallback'
            ? 'Diagram preview is unavailable. The source is shown below.' : 'Rendering diagram…'}
        </p>
      )}
      <details className="diagram-source" open={!current.svg || undefined}>
        <summary>Diagram source</summary>
        <CodeDialogBox code={code} language="mermaid" />
      </details>
    </section>
  );
}

function formatInlineMarkdown(text) {
  if (!text) return '';
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
}

function renderMarkdownTable(lines, key) {
  if (!lines || lines.length < 2) return null;
  const parseRow = (line) => {
    const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    return trimmed.split('|').map(cell => cell.trim());
  };
  const headerCells = parseRow(lines[0]);
  const isAlignRow = /^[\s|:-]+$/.test(lines[1]);
  const dataRows = isAlignRow ? lines.slice(2) : lines.slice(1);

  return (
    <div key={key} className="table-responsive">
      <table className="markdown-table">
        <thead>
          <tr>
            {headerCells.map((cell, idx) => (
              <th
                key={idx}
                dangerouslySetInnerHTML={{ __html: formatInlineMarkdown(cell) }}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((rowStr, rIdx) => {
            if (!rowStr.trim()) return null;
            const cells = parseRow(rowStr);
            return (
              <tr key={rIdx}>
                {cells.map((cell, cIdx) => (
                  <td
                    key={cIdx}
                    dangerouslySetInnerHTML={{ __html: formatInlineMarkdown(cell) }}
                  />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function renderTextMarkdown(text, keyPrefix) {
  if (!text) return null;
  const lines = text.split(/\r?\n/);
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // Horizontal Rule (---, ***, ___)
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      elements.push(<hr key={`${keyPrefix}-hr-${i}`} className="markdown-hr" />);
      i++;
      continue;
    }

    // Headings (###### down to #)
    const hMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (hMatch) {
      const level = hMatch[1].length;
      const hText = formatInlineMarkdown(hMatch[2]);
      const Heading = `h${level}`;
      elements.push(
        <Heading
          key={`${keyPrefix}-h-${i}`}
          className={`md-heading md-h${level}`}
          dangerouslySetInnerHTML={{ __html: hText }}
        />
      );
      i++;
      continue;
    }

    // Markdown Table detection: line with | and next line with |:--:|
    if (trimmed.startsWith('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1].trim())) {
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      elements.push(renderMarkdownTable(tableLines, `${keyPrefix}-tbl-${i}`));
      continue;
    }

    // Blockquote
    if (trimmed.startsWith('>')) {
      const bqText = formatInlineMarkdown(trimmed.replace(/^>\s?/, ''));
      elements.push(
        <blockquote
          key={`${keyPrefix}-bq-${i}`}
          className="md-blockquote"
          dangerouslySetInnerHTML={{ __html: bqText }}
        />
      );
      i++;
      continue;
    }

    // Unordered list
    if (/^[-*+]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*+]\s+/, ''));
        i++;
      }
      elements.push(
        <ul key={`${keyPrefix}-ul-${i}`} className="md-list">
          {items.map((item, itIdx) => (
            <li
              key={itIdx}
              dangerouslySetInnerHTML={{ __html: formatInlineMarkdown(item) }}
            />
          ))}
        </ul>
      );
      continue;
    }

    // Ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i++;
      }
      elements.push(
        <ol key={`${keyPrefix}-ol-${i}`} className="md-list md-list-ordered">
          {items.map((item, itIdx) => (
            <li
              key={itIdx}
              dangerouslySetInnerHTML={{ __html: formatInlineMarkdown(item) }}
            />
          ))}
        </ol>
      );
      continue;
    }

    // Empty line
    if (!trimmed) {
      elements.push(<div key={`${keyPrefix}-sp-${i}`} className="md-spacer" />);
      i++;
      continue;
    }

    // Regular paragraph line
    elements.push(
      <p
        key={`${keyPrefix}-p-${i}`}
        className="md-paragraph"
        dangerouslySetInnerHTML={{ __html: formatInlineMarkdown(line) }}
      />
    );
    i++;
  }

  return elements;
}

export default function MarkdownRenderer({ content, isStreaming }) {
  if (!content && !isStreaming) return null;

  const segments = markdownSegments(content);

  return (
    <div className="text-sm">
      {segments.map((seg, idx) => {
        if (seg.type === 'code') {
          if (seg.lang === 'mermaid') {
            return <MermaidDiagram key={idx} code={seg.code} complete={seg.complete} />;
          }
          return (
            <CodeDialogBox
              key={idx}
              code={seg.code}
              language={seg.lang}
            />
          );
        }
        return renderTextMarkdown(seg.content, `seg-${idx}`);
      })}
      {isStreaming && (
        <span className="streaming-cursor">▋</span>
      )}
    </div>
  );
}
