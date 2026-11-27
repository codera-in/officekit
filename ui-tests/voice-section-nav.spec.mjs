import {test,expect} from '@playwright/test';

test.beforeEach(async ({page})=>{
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    return route.continue({url:`http://127.0.0.1:19873${url.pathname}${url.search}`,
      headers:{...route.request().headers(),authorization:`Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`}});
  });
  await page.goto('/');
  await expect(page.locator('#tool-gallery-status')).not.toHaveText('Loading tools…');
  await page.evaluate(()=>switchTab('dictate'));
});

test('the Voice section list jumps to each section and marks the one in view',async({page})=>{
  const nav=page.getByRole('navigation',{name:'Voice transcription sections'});
  await expect(nav).toBeVisible();
  await expect(nav.getByRole('link')).toHaveCount(5);
  await expect(nav.getByRole('link',{name:/Speech Coach/})).toBeVisible();
  await nav.getByRole('link',{name:/Speech Coach/}).click();
  await expect(nav.getByRole('link',{name:/Speech Coach/})).toHaveAttribute('aria-current','true');
  await expect(page.locator('#speech-coach-notes-heading')).toBeFocused();
  await expect(page.locator('#speech-coach-notes-heading')).toBeInViewport();
  await expect(nav.getByRole('link',{name:/Dictation/}).first()).not.toHaveAttribute('aria-current','true');
});

test('the Voice section list keeps the screen within the approved button count',async({page})=>{
  const nav=page.getByRole('navigation',{name:'Voice transcription sections'});
  await expect(nav.getByRole('button')).toHaveCount(0);
});

test('section links are links, not buttons, so they do not count toward the button limit',async({page})=>{
  await expect(page.getByRole('navigation',{name:'Voice transcription sections'}).getByRole('link',{name:/Recent transcripts/})).toHaveAttribute('href','#dictation-history-heading');
});
