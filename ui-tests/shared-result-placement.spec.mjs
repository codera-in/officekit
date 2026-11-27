import { test, expect } from '@playwright/test';

test('shared computed, text and binary result actions follow their complete output', async ({ page }) => {
  await page.goto('/');
  const measurements = await page.evaluate(() => {
    const cases = [
      ['computed', container => officekitPublishComputedResult(container, {total: 42}, 'Computed fixture', 'layout-computed')],
      ['text', container => officekitPublishTextResult(container, 'Complete Unicode result — 終', 'Text fixture', 'layout-text')],
      ['binary', container => officekitPublishBinaryResult(container, new Blob(['fixture']), 'fixture.txt', 'Binary fixture')],
      ['calculator', container => officekitRenderCalculationActions(container, {toolId: 'roi', title: 'ROI fixture', inputs: {invested: 100, returned: 120, fees: 0}, result: {roi_percent: 20}, resultLabel: 'Difference'})],
    ];
    return cases.map(([name, mount]) => {
      const container = document.createElement('section');
      const output = document.createElement('p'); output.textContent = 'Complete result content'; output.style.minHeight = '180px';
      container.append(output); document.body.append(container); mount(container);
      const actions = container.querySelector('.officekit-result-actions');
      const result = {name, contentPreserved: output.textContent === 'Complete result content', last: container.lastElementChild === actions, afterOutput: actions.getBoundingClientRect().top >= output.getBoundingClientRect().bottom, position: getComputedStyle(actions).position};
      container.remove(); return result;
    });
  });
  for (const result of measurements) {
    expect(result.contentPreserved, result.name).toBe(true);
    expect(result.last, result.name).toBe(true);
    expect(result.afterOutput, result.name).toBe(true);
    expect(result.position, result.name).toBe('static');
  }
});
