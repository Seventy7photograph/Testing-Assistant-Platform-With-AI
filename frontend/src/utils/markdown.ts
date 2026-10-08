/**
 * 极简 Markdown 渲染器。
 *
 * 报告正文由大模型生成，属于不可信内容，所以先整体 HTML 转义，
 * 再只把白名单内的记号（标题/列表/表格/引用/代码/强调）还原成标签。
 * 不引入第三方库，也不允许任何原始标签通过。
 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function inline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
}

function isTableSeparator(line: string): boolean {
  return /^\|?[\s:-]*-[\s|:-]*\|?$/.test(line.trim()) && line.includes("-");
}

function splitRow(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

export function renderMarkdown(source: string): string {
  if (!source) return "";
  const lines = escapeHtml(source).split(/\r?\n/);
  const out: string[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const buffer: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        buffer.push(lines[index]);
        index += 1;
      }
      index += 1;
      out.push(`<pre><code>${buffer.join("\n")}</code></pre>`);
      continue;
    }

    if (/^#{1,4}\s/.test(trimmed)) {
      const level = trimmed.match(/^#+/)![0].length;
      out.push(`<h${level}>${inline(trimmed.replace(/^#+\s*/, ""))}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      out.push("<hr />");
      index += 1;
      continue;
    }

    if (trimmed.startsWith("|") && isTableSeparator(lines[index + 1] ?? "")) {
      const head = splitRow(trimmed);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      const headHtml = head.map((cell) => `<th>${inline(cell)}</th>`).join("");
      const bodyHtml = rows
        .map(
          (row) =>
            `<tr>${row
              .map((cell) => `<td>${inline(cell)}</td>`)
              .join("")}</tr>`,
        )
        .join("");
      out.push(`<table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`);
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const buffer: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        buffer.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      out.push(`<blockquote>${inline(buffer.join(" "))}</blockquote>`);
      continue;
    }

    if (/^[-*+]\s/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*+]\s/.test(lines[index])) {
        items.push(inline(lines[index].trim().replace(/^[-*+]\s/, "")));
        index += 1;
      }
      out.push(`<ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\d+[.)]\s/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+[.)]\s/.test(lines[index])) {
        items.push(inline(lines[index].trim().replace(/^\d+[.)]\s/, "")));
        index += 1;
      }
      out.push(`<ol>${items.map((item) => `<li>${item}</li>`).join("")}</ol>`);
      continue;
    }

    const paragraph: string[] = [trimmed];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,4}\s|>|\s*[-*+]\s|\s*\d+[.)]\s|\||```)/.test(lines[index].trim())
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    out.push(`<p>${inline(paragraph.join(" "))}</p>`);
  }

  return out.join("\n");
}
