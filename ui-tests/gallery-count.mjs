export async function expectGalleryMatchesCatalog(page, expect) {
  const catalog = await page.evaluate(async () => {
    const response = await fetch('/api/tools/search?q=');
    return { status: response.status, body: await response.json() };
  });

  expect(catalog.status).toBe(200);
  expect(Array.isArray(catalog.body.tools)).toBe(true);
  const count = catalog.body.tools.length;
  await expect(page.locator('#tool-gallery-status')).toHaveText(`${count} tools`);
  // Every tool, the image workbench tools included, is one card from the shared tool-card component.
  await expect(page.locator('#tool-gallery-results article')).toHaveCount(count);
  await expect(page.locator('#tool-gallery-results [data-image-tools-card]')).toHaveCount(0);
  return count;
}
