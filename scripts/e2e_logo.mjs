import { connectCdp } from './cdp.mjs';
import { reporter } from './cdp.mjs';

const base = process.argv[2] || 'http://127.0.0.1:8098';
const port = Number(process.argv[3] || 9633);
const report = reporter();

let cdp;
try {
  cdp = await connectCdp({ port });

  /* ---- login page + its logo ---- */
  await cdp.goto(`${base}/#/login`, 2800);
  const loginLogo = await cdp.evaluate(`JSON.stringify({
    img: !!document.querySelector('.login-card__logo-img'),
    src: (document.querySelector('.login-card__logo-img') || {}).src || '',
    w: (document.querySelector('.login-card__logo-img') || {}).naturalWidth || 0,
    h: (document.querySelector('.login-card__logo-img') || {}).naturalHeight || 0,
    nav: document.querySelectorAll('.nav__item').length
  })`);
  const ll = JSON.parse(loginLogo);
  report.check('登录页显示 logo 图片', ll.img, `src=${ll.src}`);
  report.check('logo 图片加载成功(有尺寸)', ll.w === 32 && ll.h === 32, `${ll.w}x${ll.h}`);
  await cdp.screenshot('.artifacts/logo-login.png');

  /* ---- login via auto-login & sidebar logo ---- */
  await cdp.goto(`${base}/api/dev/auto-login`, 1200);
  await cdp.goto(`${base}/#/dashboard`, 2800);
  const side = await cdp.evaluate(`JSON.stringify({
    img: !!document.querySelector('.sidebar__logo-img'),
    src: (document.querySelector('.sidebar__logo-img') || {}).src || '',
    w: (document.querySelector('.sidebar__logo-img') || {}).naturalWidth || 0,
    h: (document.querySelector('.sidebar__logo-img') || {}).naturalHeight || 0
  })`);
  const sl = JSON.parse(side);
  report.check('侧栏显示 logo 图片', sl.img, `src=${sl.src}`);
  report.check('侧栏 logo 加载成功', sl.w === 32, `${sl.w}x${sl.h}`);
  await cdp.screenshot('.artifacts/logo-sidebar.png');

  /* ---- favicon served ---- */
  const fav = await (await fetch(`${base}/favicon.ico`)).ok;
  report.check('favicon.ico 可访问', fav === true, `${base}/favicon.ico`);
  const png = await (await fetch(`${base}/logo.png`)).ok;
  report.check('logo.png 可访问', png === true, `${base}/logo.png`);

  report.check('无 JS 控制台错误', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 2).join(' | '));
} catch (error) {
  console.error('\n[异常]', error && error.stack ? error.stack : error);
  report.check('套件执行未抛异常', false, String((error && error.message) || error).slice(0, 160));
} finally {
  if (cdp) cdp.close();
  if (report.summary() > 0) process.exit(1);
}