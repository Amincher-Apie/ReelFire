const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const projectRoot = path.resolve(__dirname, '..');
const screenshotDir = path.join(projectRoot, 'docs', 'Acceptance_screenshot');
const normalVideo = path.join(projectRoot, 'tests', 'test_assets', 'gameplay_normal.mp4');
const baseUrl = process.env.REELFIRE_BASE_URL || 'http://127.0.0.1:7880';

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function fillJobForm(page, { name, video, interval = '2', ratio = '16:9' }) {
  await page.fill('#project-name', name);
  await page.selectOption('#game-type', 'csgo');
  await page.setInputFiles('#video-file', video);
  await page.fill('#sample-interval', interval);
  await page.fill('#target-duration', '15');
  await page.selectOption('#output-aspect', ratio);
}

async function main() {
  fs.mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    channel: 'msedge',
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = [];
  const failedResponses = [];
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`);
  });
  page.on('pageerror', (error) => browserErrors.push(`page: ${error.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.waitForSelector('#upload-form', { state: 'visible' });
    await page.screenshot({
      path: path.join(screenshotDir, '01_upload_ready.png'),
      fullPage: true,
    });

    let delayFirstListRequest = true;
    await page.route('**/api/jobs', async (route) => {
      if (delayFirstListRequest && route.request().method() === 'GET') {
        delayFirstListRequest = false;
        await wait(1200);
      }
      await route.continue();
    });
    await page.click('#nav-task-list');
    await page.waitForSelector('#task-list-loading', { state: 'visible' });
    await page.screenshot({
      path: path.join(screenshotDir, '02_loading.png'),
      fullPage: true,
    });
    await page.waitForSelector('#task-list-loading', { state: 'hidden' });
    await page.unroute('**/api/jobs');

    await page.click('#nav-new-task');
    await fillJobForm(page, {
      name: 'CS2 浏览器验收-正常流程',
      video: normalVideo,
      interval: '0.25',
      ratio: '16:9',
    });
    await page.click('#btn-create');
    await page.waitForSelector('#view-task-list.active', { state: 'visible' });
    const completedJobId = await page.evaluate(() => STATE.currentJobId);
    await page.evaluate((jobId) => openTask(jobId), completedJobId);
    await page.waitForSelector('#view-task-detail.active', { state: 'visible' });
    await page.waitForSelector('#detail-running', { state: 'visible', timeout: 30000 });
    await page.screenshot({
      path: path.join(screenshotDir, '03_running.png'),
      fullPage: true,
    });

    await page.waitForSelector('#detail-completed', {
      state: 'visible',
      timeout: 240000,
    });
    await page.waitForSelector('.keyframe-card img', { state: 'visible' });
    await page.screenshot({
      path: path.join(screenshotDir, '04_completed.png'),
      fullPage: true,
    });
    await page.locator('.keyframe-card').first().screenshot({
      path: path.join(screenshotDir, '05_detection_keyframe.png'),
    });

    await page.locator('button', { hasText: '查看 JSON 报告' }).click();
    await page.waitForSelector('#report-modal', { state: 'visible' });
    const browserReport = JSON.parse(await page.textContent('#report-content'));
    if (!browserReport.segment_tags || !browserReport.ai_cover_prompt) {
      throw new Error('analysis report is missing segment_tags or ai_cover_prompt');
    }
    await page.locator('#report-modal button', { hasText: '×' }).click();
    await page.waitForSelector('#report-modal', { state: 'hidden' });

    await page.locator('.keyframe-card').first().locator('.kf-decision button').nth(1).click();
    await page.locator('.keyframe-card').nth(1).locator('.kf-label-select').selectOption('clutch');
    await page.locator('.keyframe-card').nth(1).locator('.kf-note').fill('浏览器验收：保留残局候选');
    await page.click('#btn-save-review');
    await page.waitForFunction(() => {
      const toast = document.querySelector('.toast');
      return toast && toast.textContent.includes('审核结果已保存');
    });

    await page.click('#btn-rough-cut');
    await page.waitForSelector('#detail-output video', {
      state: 'visible',
      timeout: 120000,
    });
    await page.screenshot({
      path: path.join(screenshotDir, '06_output_video.png'),
      fullPage: true,
    });

    const corruptVideo = path.join(os.tmpdir(), `reelfire-corrupt-${Date.now()}.mp4`);
    const corruptPayload = Buffer.alloc(96);
    corruptPayload.writeUInt32BE(28, 0);
    corruptPayload.write('ftypisom', 4, 'ascii');
    fs.writeFileSync(corruptVideo, corruptPayload);
    try {
      await page.click('#nav-new-task');
      await fillJobForm(page, {
        name: 'CS2 浏览器验收-损坏视频',
        video: corruptVideo,
        interval: '2',
        ratio: '9:16',
      });
      await page.click('#btn-create');
      await page.waitForSelector('#view-task-list.active', { state: 'visible' });
      const failedJobId = await page.evaluate(() => STATE.currentJobId);
      await page.evaluate((jobId) => openTask(jobId), failedJobId);
      await page.waitForSelector('#detail-failed', {
        state: 'visible',
        timeout: 60000,
      });
      await page.screenshot({
        path: path.join(screenshotDir, '07_failed.png'),
        fullPage: true,
      });

      await page.click('#nav-task-list');
      await page.waitForSelector('#task-list-table', { state: 'visible' });
      await page.screenshot({
        path: path.join(screenshotDir, '08_task_history.png'),
        fullPage: true,
      });

      const result = {
        ok: browserErrors.length === 0 && failedResponses.length === 0,
        completed_job_id: completedJobId,
        failed_job_id: failedJobId,
        screenshots: fs.readdirSync(screenshotDir).sort(),
        browser_errors: browserErrors,
        failed_responses: failedResponses,
      };
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
      if (!result.ok) process.exitCode = 1;
    } finally {
      fs.rmSync(corruptVideo, { force: true });
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
