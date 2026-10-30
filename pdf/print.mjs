import { readFileSync } from 'node:fs';

const STATIC_FALLBACKS = {
  './interactive/unit-yield.html': './images/figures/generated/supplementary-neuropixels-unit-yield.svg',
  './interactive/eye-tracking-viewer.html': './images/figures/generated/synchronized-eye-tracking.svg',
};

function text(value) {
  return { type: 'text', value };
}

function raw(typst) {
  return { type: 'raw', typst };
}

function printTable(node) {
  const identifier = node.identifier ?? node.label;
  const rows = node.children.filter((child) => child.type === 'tableRow');
  const columns = rows[0].children.reduce((count, cell) => count + (cell.colspan ?? 1), 0);
  const widths = columns === 2 ? '(1fr, 2fr)' : `(${Array(columns).fill('1fr').join(',')},)`;
  const children = [raw(`#{\nset text(size: 8.3pt)\nset par(justify: false)\ntable(columns: ${widths}, inset: 5pt, align: left, stroke: 0.35pt + luma(190),\n`)];
  for (const row of rows) {
    const header = row.children.every((cell) => cell.header);
    if (header) children.push(raw('table.header(\n'));
    for (const cell of row.children) {
      const span = `colspan: ${cell.colspan ?? 1}, rowspan: ${cell.rowspan ?? 1}`;
      children.push(raw(`table.cell(${span})[\n`));
      if (header) children.push(raw('#strong[\n'));
      children.push(...cell.children);
      if (header) children.push(raw('\n]'));
      children.push(raw('\n],\n'));
    }
    if (header) children.push(raw('),\n'));
  }
  const label = identifier ? ` #label(${JSON.stringify(identifier)})` : '';
  children.push(raw(`)\n}${label}\n\n`));
  return { ...node, type: 'div', children };
}

function printFigure(node) {
  const caption = node.children.find((child) => child.type === 'caption');
  const pictures = node.children.filter((child) => child.type !== 'caption').flatMap((child) => (
    child.type === 'iframe' ? child.children ?? [] : [child]
  ));
  if (!pictures.length) {
    throw new Error(`Missing static PDF content for ${node.identifier ?? node.label}.`);
  }
  const figure = {
    ...node,
    children: [...pictures, ...(caption ? [caption] : [])],
  };
  if (node.enumerated === false) {
    return {
      type: 'div',
      children: [
        raw('#[\n#set figure(numbering: none)\n'),
        figure,
        raw('\n]\n'),
      ],
    };
  }
  return figure;
}

function printLiterature(node, manifest) {
  const rows = manifest.literature?.rows;
  if (!rows?.length) throw new Error('Prepare the PDF assets before exporting the literature table.');
  const title = 'Supplementary Table 1';
  const identifier = node.identifier ?? node.label;
  const children = [
    raw(`#pagebreak(weak: true)\n#block[${title}. Published oddball paradigms and sampling parameters] #label(${JSON.stringify(identifier)})\n\n`),
  ];
  for (let column = 1; column < rows[0].length; column += 1) {
    const heading = { type: 'paragraph', children: [{ type: 'strong', children: [text(rows[0][column])] }] };
    const table = {
      type: 'table',
      children: [
        ['Parameter', rows[0][column]],
        ...rows.slice(1).map((row) => [row[0], row[column]]),
      ].map((row, index) => ({
        type: 'tableRow',
        children: row.map((value) => ({
          type: 'tableCell', header: index === 0,
          children: [{ type: 'paragraph', children: [text(value)] }],
        })),
      })),
    };
    children.push(raw('#printStudy[\n'), heading, printTable(table), raw('\n]\n\n'));
  }
  return { ...node, type: 'div', children };
}

export function authorNodes(model) {
  const { primary: contributors } = JSON.parse(model.authors);
  if (!Array.isArray(contributors) || contributors.length === 0) {
    throw new Error('The print author list requires the portal-backed contributor snapshot.');
  }
  const affiliations = [];
  const names = [];
  for (const contributor of contributors) {
    if (names.length) names.push(text(', '));
    const name = text(contributor.name);
    names.push(contributor.orcid
      ? { type: 'link', url: `https://orcid.org/${contributor.orcid}`, children: [name] }
      : name);
    const indices = (contributor.affiliations ?? []).map((affiliation) => {
      const name = typeof affiliation === 'string' ? affiliation : affiliation.name;
      if (!affiliations.includes(name)) affiliations.push(name);
      return affiliations.indexOf(name) + 1;
    });
    if (indices.length) {
      names.push({ type: 'superscript', children: [text(indices.join(','))] });
    }
  }
  return [
    raw(`#set document(author: (${contributors.map((author) => JSON.stringify(author.name)).join(',')},))\n`),
    raw('#printAuthors[\n'),
    { type: 'paragraph', children: names },
    raw('][\n'),
    ...affiliations.map((name, index) => ({
      type: 'paragraph',
      children: [{ type: 'superscript', children: [text(String(index + 1))] }, text(` ${name}`)],
    })),
    raw('\n]\n\n'),
  ];
}

export function preparePrintTree(tree, manifest = {}) {
  const authors = [];
  function expand(children) {
    return children.flatMap((node) => {
      if (node.type === 'anywidget' && node.model?.authors) {
        authors.push(...authorNodes(node.model));
        return [];
      }
      if (node.type === 'summary') return [];
      if (node.type === 'iframe' && STATIC_FALLBACKS[node.src]) {
        node.children = [{
          type: 'image',
          url: STATIC_FALLBACKS[node.src],
          alt: node.title,
          width: '100%',
          placeholder: true,
        }];
      }
      if (node.children) node.children = expand(node.children);
      if (node.type === 'image') {
        node.width = '100%';
        delete node.height;
      }
      if (node.type === 'details') return node.children ?? [];
      if (node.type === 'table') return [printTable(node)];
      if (node.type === 'container' && node.kind === 'table') {
        const caption = node.children.find((child) => child.type === 'caption');
        const identifier = node.identifier ?? node.label;
        return [{
          ...node,
          type: 'div',
          children: [
            raw('#block[\n'),
            ...(caption?.children ?? []),
            raw(`\n] #label(${JSON.stringify(identifier)})\n\n`),
            ...node.children.filter((child) => child.type !== 'caption'),
          ],
        }];
      }
      if (node.type === 'container' && node.kind === 'figure') {
        if ((node.identifier ?? node.label) === 'table-supplementary-oddball-studies') {
          return [printLiterature(node, manifest)];
        }
        return [printFigure(node)];
      }
      return [node];
    });
  }
  tree.children = expand(tree.children ?? []);
  tree.children.unshift(...authors);
}

export default {
  name: 'OpenScope PDF-only presentation',
  transforms: [{
    name: 'openscope-print-content',
    stage: 'document',
    plugin: () => (tree) => {
      const path = new URL('../_build/pdf-assets/manifest.json', import.meta.url);
      preparePrintTree(tree, JSON.parse(readFileSync(path, 'utf8')));
    },
  }],
};