// Playwright global setup: push an entitlement to the test sidecar the way the native shell does,
// so paid API routes are reachable. The licence gate itself stays on.
// NOTE (QA-5b): the pushed entitlement lives for `valid_for_seconds: 3600` on the sidecar's monotonic
// clock and is pushed once, here, per Playwright invocation. A single run that lasts longer than an hour
// (all projects together) lets it lapse and every paid route then answers 403 `license_required`. Split
// such a run, or re-run this setup, rather than reading those 403s as product failures.
export default async function installUiTestEntitlement() {
  const apiPort = process.env.OFFICEKIT_UI_TEST_API_PORT || '19873';
  const response = await fetch(`http://127.0.0.1:${apiPort}/api/license/entitlement`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${process.env.OFFICEKIT_UI_TEST_TOKEN}`,
      'Content-Type': 'application/json',
      'X-OfficeKit-Native-Grant': process.env.OFFICEKIT_UI_TEST_NATIVE_GRANT_TOKEN,
    },
    body: JSON.stringify({
      activation_id: 'uiTestActivationId0001',
      edition: 'paid',
      features: [],
      valid_for_seconds: 3600,
    }),
  });
  if (response.status !== 204) {
    throw new Error(`UI test entitlement push failed with HTTP ${response.status}.`);
  }
}
