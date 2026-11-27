import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

function makePdf(pages) {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${3 + i * 2} 0 R`).join(' ')}] /Count ${pages.length} >>`];
  for (let index = 0; index < pages.length; index += 1) {
    const pageObject = 3 + index * 2;
    const streamObject = pageObject + 1;
    const textCommands = pages[index].map((text, line) => `BT /F1 12 Tf 1 0 0 1 40 ${740 - line * 18} Tm (${text.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)')}) Tj ET`).join('\n');
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 450 780] /Resources << /Font << /F1 ${3 + pages.length * 2} 0 R >> >> /Contents ${streamObject} 0 R >>`);
    objects.push(`<< /Length ${Buffer.byteLength(textCommands, 'ascii')} >>\nstream\n${textCommands}\nendstream`);
  }
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  const chunks = [Buffer.from('%PDF-1.4\n', 'ascii')];
  const offsets = [0];
  let length = chunks[0].length;
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(length);
    const chunk = Buffer.from(`${index + 1} 0 obj\n${objects[index]}\nendobj\n`, 'ascii');
    chunks.push(chunk);
    length += chunk.length;
  }
  const xrefOffset = length;
  const xref = [`xref\n0 ${objects.length + 1}\n`, '0000000000 65535 f \n'];
  for (const offset of offsets.slice(1)) xref.push(`${String(offset).padStart(10, '0')} 00000 n \n`);
  xref.push(`trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`);
  chunks.push(Buffer.from(xref.join(''), 'ascii'));
  return Buffer.concat(chunks);
}

test.beforeEach(async ({ context, page }) => {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:19874') await route.abort();
    else if (url.pathname.startsWith('/api/')) await route.continue({
      url: `http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers: { ...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}` },
    });
    else await route.continue();
  });
  await page.goto('/');
});

test('PDF text extraction previews selected pages in order and downloads Markdown', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-pdf-text-'));
  try {
    const source = makePdf([['First page text'], ['Second page text']]);
    const sourcePath = path.join(root, 'report.pdf');
    await fs.writeFile(sourcePath, source);
    await page.evaluate(() => openPdfTool('text', false));
    await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
    await page.locator('#pdf-text-page-ranges').fill('2, 1');
    await page.locator('#pdf-text-format').selectOption('md');
    await page.getByRole('button', { name: 'Extract text' }).click();
    const preview = page.locator('#pdf-text-preview');
    await expect(preview).toContainText('Second page text');
    await expect.poll(() => page.evaluate(() => {
      const panel = document.getElementById('pdf-workbench-preview')?.getBoundingClientRect();
      const workArea = document.getElementById('app-main')?.getBoundingClientRect();
      const dock = document.getElementById('officekit-tool-actions')?.getBoundingClientRect();
      return Boolean(panel && workArea && dock && panel.top >= workArea.top - 1 && panel.bottom <= dock.top - 8);
    })).toBe(true);
    const previewText = await preview.textContent();
    expect(previewText.indexOf('Page 2')).toBeLessThan(previewText.indexOf('Page 1'));
    await expect(page.locator('#pdf-workbench-preview-text')).toContainText('2 selected pages of 2');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#pdf-text-preview').locator('xpath=..').locator('.officekit-result-actions button').nth(1).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe('report_text.md');
    const output = await fs.readFile(await download.path(), 'utf8');
    expect(output.indexOf('Page 2')).toBeLessThan(output.indexOf('Page 1'));
    expect(await fs.readFile(sourcePath)).toEqual(source);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('PDF text extraction reports scanned-only PDFs without enabling a download', async ({ page }) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'officekit-pdf-text-scan-'));
  try {
    const sourcePath = path.join(root, 'scan.pdf');
    await fs.writeFile(sourcePath, makePdf([[]]));
    await page.evaluate(() => openPdfTool('text', false));
    await page.locator('#pdf-workbench-file-input').setInputFiles(sourcePath);
    await page.getByRole('button', { name: 'Extract text' }).click();
    await expect(page.locator('#pdf-workbench-status')).toContainText('scanned image PDF');
    await expect(page.getByRole('button', { name: 'Download output' })).toBeHidden();
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
