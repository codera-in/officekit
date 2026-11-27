// Shared native bridge stub for UI specs that need the lock state.
// NOTE (QA-5a): a spec that defines its own `window.__TAURI__` WITHOUT this stub never answers
// `license_state`. The app maps an unanswered/unreadable `license_state` to state 'none', which the UI
// treats as UNGATED (no chips, no guard, no banner). That is a UI-only fail-open by design (the sidecar
// and native commands still enforce), so such specs do not see an ACTIVE or LOCKED app; they see no gate.
// Specs that assert lock behaviour, or want an explicitly active app, must call stubNativeLicense().
// `license_state` answers with window.__officekitLicenseState ('active' unless the spec says otherwise).
// While that state is not 'active' every other command is rejected with `license_required`, the way the
// Rust gate rejects paid native commands. Specs that stub `window.__TAURI__` themselves and never answer
// `license_state` are left ungated by the app (an unreadable state is treated as "no gate to show").
export async function stubNativeLicense(page, state = 'active') {
  await page.addInitScript(initialState => {
    const alwaysAllowed = new Set(['license_state', 'license_status', 'license_activate', 'license_deactivate']);
    window.__officekitLicenseState = initialState;
    window.__officekitInvokeLog = [];
    window.__officekitDeactivateCalls = [];
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          window.__officekitInvokeLog.push(command);
          if (command === 'license_deactivate') {
            window.__officekitDeactivateCalls.push(args);
            // A spec sets this to make the service unreachable or reject the credentials.
            if (window.__officekitDeactivateError) throw window.__officekitDeactivateError;
            window.__officekitLicenseState = 'locked';
            return null;
          }
          if (command === 'license_state') {
            if (window.__officekitLicenseStateDelayMs) await new Promise(resolve => setTimeout(resolve, window.__officekitLicenseStateDelayMs));
            return window.__officekitLicenseState;
          }
          if (command === 'license_status') return { device_slots_used: 1, device_slots_allowed: 3 };
          if (window.__officekitLicenseState !== 'active' && !alwaysAllowed.has(command)) throw 'license_required';
          return command === 'dictation_model_inventory' ? [] : null;
        },
      },
      event: { listen: async () => () => {} },
    };
  }, state);
}

// Changes what the stub reports and makes the page re-read it, as the 60-second timer or a focus would.
export async function setNativeLicenseState(page, state) {
  await page.evaluate(async next => {
    window.__officekitLicenseState = next;
    await checkLicenseStatus();
  }, state);
}
