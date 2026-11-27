import { expect, test } from '@playwright/test';
import { routeAuthenticatedApi, waitForAppReady } from './authenticated-app.mjs';

test('Speech Coach shows real session measures, language suggestions and a baseline state', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
  await page.evaluate(() => switchTab('dictate'));
  await expect(page.locator('#speech-coach-notes-heading')).toBeVisible();
  await page.evaluate(async () => {
    const session = {
      id: 'coach-session-1',
      context: 'casual',
      focus: 'grammar',
      recognizedWords: 40,
      fillerWords: 2,
      paceWpm: 120,
      pitchMedianHz: 123,
      grammarSuggestions: 2,
      vocabularySuggestions: 0,
      languagePatterns: ['grammar.subject_verb', 'grammar.subject_verb'],
      dismissedPatterns: [],
      usefulPatterns: [],
      speechSeconds: 20,
    };
    window.__coachCalls = [];
    window.__TAURI__ = {
      core: {
        invoke: async (command, args) => {
          window.__coachCalls.push([command, args]);
          if (command === 'speech_coach_status') return {
            settings: { enabled: true, paused: false, context: 'casual', focus: 'grammar', placement: 'top_center', overlayVisible: true, targetPaceMin: 110, targetPaceMax: 160 },
            state: 'enabled',
            languageModelAvailable: false,
          };
          if (command === 'speech_coach_notes') return [session];
          return null;
        },
      },
    };
    initializeSpeechCoachNotes();
    await refreshSpeechCoachNotes();
  });

  await expect(page.locator('#speech-coach-enabled')).toBeChecked();
  await expect(page.locator('#speech-coach-session-count')).toHaveText('1');
  await expect(page.locator('#speech-coach-pitch-trend')).toHaveText('123 Hz');
  await expect(page.locator('#speech-coach-patterns')).toContainText('subject–verb agreement appeared 2 times');
  await expect(page.locator('#speech-coach-status')).toContainText('on-device language model');
  await expect(page.locator('#speech-coach-retrospective')).toContainText('Progress will appear after four comparable sessions');
  await expect(page.getByRole('combobox', { name: 'Next-session focus' }).locator('option')).toHaveCount(5);
  await expect(page.locator('#speech-coach-pace-zone option')).toHaveCount(7);
  await page.locator('#speech-coach-pace-zone').selectOption('120-170');
  await expect.poll(() => page.evaluate(() => window.__coachCalls.some(([command, args]) => command === 'speech_coach_configure' && args?.settings?.targetPaceMin === 120 && args?.settings?.targetPaceMax === 170))).toBe(true);
});

test('a saved note explains the rule behind a repeated pattern, and a dismissed pattern hides it', async ({ page }) => {
  await routeAuthenticatedApi(page);
  await page.goto('/');
  await waitForAppReady(page);
  await page.evaluate(() => switchTab('dictate'));
  await page.evaluate(async () => {
    const session = { id: 'coach-session-2', context: 'casual', focus: 'grammar', recognizedWords: 40, fillerWords: 0, paceWpm: 120, grammarSuggestions: 2, vocabularySuggestions: 0, languagePatterns: ['grammar.subject_verb', 'grammar.subject_verb'], dismissedPatterns: [], usefulPatterns: [], speechSeconds: 20 };
    const rules = [{ id: 'grammar.subject_verb', title: 'Subject–verb agreement', rule: 'A plural subject takes a plural verb (are, were, have). Only a singular subject takes is, was or has.', wrong: 'The prices is low.', right: 'The prices are low.' }];
    window.__session = session;
    window.__TAURI__ = { core: { invoke: async command => {
      if (command === 'speech_coach_status') return { settings: { enabled: true, paused: false, context: 'casual', focus: 'grammar', placement: 'top_center', overlayVisible: true, targetPaceMin: 110, targetPaceMax: 160 }, state: 'enabled', languageModelAvailable: false };
      if (command === 'speech_coach_notes') return [window.__session];
      if (command === 'speech_coach_rules') return rules;
      return null;
    } } };
    initializeSpeechCoachNotes();
    await refreshSpeechCoachNotes();
  });
  const rule = page.locator('[data-speech-coach-rule="grammar.subject_verb"]');
  await expect(rule).toContainText('A plural subject takes a plural verb (are, were, have).');
  await expect(rule.locator('span')).toHaveText([
    'Rule: A plural subject takes a plural verb (are, were, have). Only a singular subject takes is, was or has.',
    'Not: The prices is low.',
    'Say: The prices are low.'
  ]);
  await page.evaluate(async () => { window.__session = { ...window.__session, dismissedPatterns: ['grammar.subject_verb'] }; await refreshSpeechCoachNotes(); });
  await expect(rule).toHaveCount(0);
});
