export async function routeAuthenticatedApi(page) {
  const apiPort = process.env.OFFICEKIT_UI_TEST_API_PORT || '19873';
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    return route.continue({url: `http://127.0.0.1:${apiPort}${url.pathname}${url.search}`,
      headers: {...route.request().headers(), authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`}});
  });
}

export async function waitForAppReady(page) {
  await page.waitForFunction(() => document.readyState === 'complete' && typeof switchTab === 'function');
}
