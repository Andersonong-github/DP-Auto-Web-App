import { connectCdp, reporter } from './cdp.mjs';

const base = process.argv[2] || 'http://10.10.7.230:8080';
const port = Number(process.argv[3] || 9755);
const report = reporter();

let cdp;
try {
  cdp = await connectCdp({ port });

  // Load the login page — if JS runs without fatal import errors, the login card renders
  await cdp.goto(`${base}/#/login`, 3200);

  const state = await cdp.evaluate(`JSON.stringify({
    title: document.title,
    hasLoginCard: !!document.querySelector('.login-card'),
    hasApp: !!document.querySelector('#app') && document.querySelector('#app').children.length > 0,
    bodyText: (document.body.textContent || '').slice(0, 120)
  })`);
  const s = JSON.parse(state);
  report.check('页面标题正确', s.title.includes('Deltapath'), s.title);
  report.check('登录卡渲染(JS无致命错误)', s.hasLoginCard === true, `children=${s.hasApp}`);
  report.check('页面有内容', s.hasApp === true, s.bodyText.slice(0, 60));
  await cdp.screenshot('.artifacts/check-live-page.png');
  report.check('无 JS 控制台错误', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 2).join(' | '));
} catch (error) {
  console.error('异常:', error && error.message ? error.message : error);
  report.check('执行未抛异常', false, String((error && error.message) || error).slice(0, 160));
} finally {
  if (cdp) cdp.close();
  process.exit(report.summary() > 0 ? 1 : 0);
}