import { Fragment, type ReactNode } from "react";

/** Agents answer in light Markdown. Show it as text with structure - bold, `code`, quotes, lists, headings - built as
 *  React elements (never HTML from the answer, so nothing in it can run). */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(m[1] !== undefined ? <b key={m.index}>{m[1]}</b> : <code key={m.index}>{m[2]}</code>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Rich({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={`l${blocks.length}`}>{list.map((x, i) => <li key={i}>{inline(x)}</li>)}</ul>);
    list = [];
  };
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trimEnd();
    const item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (item) { list.push(item[1]); return; }
    flush();
    if (!line.trim()) return;
    const head = line.match(/^#{1,4}\s+(.*)$/);
    if (head) blocks.push(<p key={i} className="rich-h">{inline(head[1])}</p>);
    else if (line.startsWith(">")) blocks.push(<blockquote key={i}>{inline(line.replace(/^>\s?/, ""))}</blockquote>);
    else blocks.push(<p key={i}>{inline(line)}</p>);
  });
  flush();
  return <div className="rich" dir="auto">{blocks.map((b, i) => <Fragment key={i}>{b}</Fragment>)}</div>;
}
