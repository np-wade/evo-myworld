// ip_driver.mjs — subprocess bridge into the Information Processer incumbent.
// Usage: node ip_driver.mjs <stage>   (JSON request on stdin, JSON result on stdout)
// Stages: extract | split | concepts | research | combine | citations | docx | latex
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const serverDir = resolve(
  process.env.IP_SERVER_DIR
    ?? new URL('../../../../information-processer/server', import.meta.url).pathname,
);

const pipeline = await import(new URL(`file://${serverDir}/pipeline.mjs`));
const docx = await import(new URL(`file://${serverDir}/docx.mjs`));

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

const stage = process.argv[2];
const req = await readStdin();

async function run() {
  switch (stage) {
    case 'extract': {
      const buffer = await readFile(req.file);
      const result = pipeline.extractDocument(buffer, req.name ?? req.file, req.mime ?? '');
      return { ok: true, ...result };
    }
    case 'split': {
      const sections = pipeline.splitDocument(
        { id: req.documentId ?? 'fx', content: req.content },
        req.sensitivity ?? 0.8,
      );
      return { ok: true, sections };
    }
    case 'concepts': {
      const concepts = pipeline.extractConcepts(req.sections, req.documentId ?? 'fx');
      return { ok: true, concepts };
    }
    case 'research': {
      const result = pipeline.researchConcept(req.concept, req.documents);
      return { ok: true, research: result };
    }
    case 'graph': {
      const result = pipeline.buildGraph(req.concepts ?? [], req.researchByConcept ?? {});
      return { ok: true, graph: result };
    }
    case 'draft': {
      const drafts = pipeline.generateDrafts(
        req.sections ?? [], req.concepts ?? [], req.researchByConcept ?? {},
        req.template ?? 'arXiv Academic Paper',
      );
      return { ok: true, drafts };
    }
    case 'combine': {
      const result = pipeline.combineDrafts(req.drafts);
      return { ok: true, combined: result };
    }
    case 'citations': {
      const citations = pipeline.collectCitations(req.researchByConcept ?? {});
      return {
        ok: true,
        citations,
        bibtex: pipeline.formatBibtex(citations),
        rendered: pipeline.renderCitations(req.markdown ?? '', citations, req.style ?? 'IEEE'),
      };
    }
    case 'docx': {
      const bytes = docx.createDocx(req.markdown ?? '', req.citations ?? [], req.options ?? {});
      return { ok: true, base64: Buffer.from(bytes).toString('base64') };
    }
    case 'latex': {
      const bytes = docx.createLatexBundle(req.markdown ?? '', req.citations ?? [], req.options ?? {});
      return { ok: true, base64: Buffer.from(bytes).toString('base64') };
    }
    default:
      return { ok: false, error: `unknown stage: ${stage}` };
  }
}

try {
  const result = await run();
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
  process.exitCode = 3;
}
