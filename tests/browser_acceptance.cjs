const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const projectRoot = path.resolve(__dirname, '..');
const screenshotDir = process.env.REELFIRE_SCREENSHOT_DIR
  || path.join(os.tmpdir(), 'reelfire-browser-acceptance');
const normalVideo = path.join(
  projectRoot,
  'tests',
  'test_assets',
  'gameplay_normal.mp4',
);
const baseUrl = process.env.REELFIRE_BASE_URL || 'http://127.0.0.1:7880';

async function register(page) {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 10000)}`;
  const username = `browser_test_${suffix}`;
  const password = 'ReelFireBrowserTest!1';

  await page.getByRole('tab', { name: '注册', exact: true }).click();
  await page.fill('#register-username', username);
  await page.fill('#register-password', password);
  await page.fill('#register-confirm', password);
  await page.getByRole('button', { name: '创建账号', exact: true }).click();
  await page.waitForSelector('#show-create-project-button', {
    state: 'visible',
  });
  return username;
}

async function createAnalysisJob(page, projectName) {
  await page.click('#show-create-project-button');
  await page.waitForSelector('#project-dialog', { state: 'visible' });
  await page.fill('#project-name', projectName);
  await page.selectOption('#game-type', 'csgo');
  await page.setInputFiles('#video-file', normalVideo);
  await page.fill('#sample-interval', '0.5');
  await page.fill('#target-duration', '15');
  await page.selectOption('#output-ratio', '16:9');
  await page.click('#analyze-button');
  await page.waitForSelector('#view-analysis.active', { state: 'visible' });
  await page.waitForSelector('#result-loading', { state: 'visible' });
}

async function main() {
  fs.rmSync(screenshotDir, { recursive: true, force: true });
  fs.mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    channel: 'msedge',
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = [];
  const failedResponses = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      browserErrors.push(`console: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => browserErrors.push(`page: ${error.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    const username = await register(page);
    const projectName = `浏览器验收项目 ${Date.now()}`;
    await page.screenshot({
      path: path.join(screenshotDir, '01_projects_empty.png'),
      fullPage: true,
    });

    await createAnalysisJob(page, projectName);
    await page.waitForSelector('#analysis-progress-detail', {
      state: 'visible',
      timeout: 30000,
    });
    await page.screenshot({
      path: path.join(screenshotDir, '02_analysis_running.png'),
      fullPage: true,
    });

    await page.waitForSelector('#result-content', {
      state: 'visible',
      timeout: 240000,
    });
    await page.waitForSelector('.keyframe-card img', {
      state: 'visible',
      timeout: 30000,
    });
    if (await page.locator('#segment-list .segment-item').count() > 5) {
      throw new Error('analysis candidate list rendered more than five items');
    }
    if (await page.locator('#keyframe-list .keyframe-card').count() > 5) {
      throw new Error('keyframe review rendered more than five items');
    }
    if (await page.getAttribute('#keyframe-mode-segment', 'aria-pressed') !== 'true') {
      throw new Error('single-segment keyframe review is not the default mode');
    }
    await page.click('#keyframe-mode-all');
    if (await page.getAttribute('#keyframe-mode-all', 'aria-pressed') !== 'true') {
      throw new Error('all-keyframes review mode did not activate');
    }
    const allModeFrameIndexes = await page
      .locator('#keyframe-list .keyframe-card')
      .evaluateAll((cards) => cards.map((card) => card.dataset.frameIndex));
    const candidate = page.locator('#segment-list .segment-item').first();
    if (await candidate.count()) {
      await candidate.click();
      const afterCandidateClick = await page
        .locator('#keyframe-list .keyframe-card')
        .evaluateAll((cards) => cards.map((card) => card.dataset.frameIndex));
      if (JSON.stringify(afterCandidateClick) !== JSON.stringify(allModeFrameIndexes)) {
        throw new Error('candidate selection changed keyframes while all mode was active');
      }
    }
    await page.click('#keyframe-mode-segment');
    if (await page.getAttribute('#keyframe-mode-segment', 'aria-pressed') !== 'true') {
      throw new Error('single-segment keyframe review mode did not reactivate');
    }
    await page.screenshot({
      path: path.join(screenshotDir, '03_analysis_completed.png'),
      fullPage: true,
    });

    await page.click('#open-report-button');
    await page.waitForSelector('#report-dialog[open]', { state: 'visible' });
    const report = JSON.parse(await page.textContent('#report-content'));
    if (!Array.isArray(report.segments) || !Array.isArray(report.keyframes)) {
      throw new Error('analysis report is missing segments or keyframes');
    }
    await page.click('#close-report-button');

    await page.click('#nav-projects');
    await page.waitForSelector('#view-projects.active', { state: 'visible' });
    await page.waitForSelector('#projects-grid .project-card', {
      state: 'visible',
    });
    if (await page.locator('#projects-grid .project-card').count() > 10) {
      throw new Error('project grid rendered more than ten items');
    }
    const cardText = await page
      .locator('#projects-grid .project-card')
      .filter({ hasText: projectName })
      .innerText();
    await page.click('#project-view-list');
    await page.waitForSelector('#projects-list', { state: 'visible' });
    const rowText = await page
      .locator('#projects-list-body tr')
      .filter({ hasText: projectName })
      .innerText();
    const assetName = path.basename(normalVideo);
    if (!cardText.includes(assetName) || !rowText.includes(assetName)) {
      throw new Error('project card/list material names are inconsistent');
    }

    await page.click('#nav-analysis');
    await page.waitForSelector('#view-analysis.active', { state: 'visible' });
    const editorHref = await page.getAttribute('#editor-link', 'href');
    if (!editorHref || !editorHref.endsWith('/editor')) {
      throw new Error('completed analysis has no editor link');
    }
    await page.goto(new URL(editorHref, baseUrl).toString(), {
      waitUntil: 'domcontentloaded',
    });
    await page.waitForSelector('#editor-content', {
      state: 'visible',
      timeout: 30000,
    });
    await page.waitForSelector('.segment-card', { state: 'visible' });
    if (await page.locator('#highlight-list .segment-card').count() > 5) {
      throw new Error('editor highlight list rendered more than five items');
    }
    await page.screenshot({
      path: path.join(screenshotDir, '04_editor_ready.png'),
      fullPage: true,
    });

    const result = {
      ok: browserErrors.length === 0 && failedResponses.length === 0,
      username,
      project_name: projectName,
      report_segments: report.segments.length,
      report_keyframes: report.keyframes.length,
      screenshots: fs.readdirSync(screenshotDir).sort(),
      browser_errors: browserErrors,
      failed_responses: failedResponses,
    };
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (!result.ok) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
