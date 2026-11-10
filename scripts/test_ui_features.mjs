import { connectCdp, reporter } from './cdp.mjs';

const base = process.argv[2] || 'http://10.10.7.230:8080';
const port = Number(process.argv[3] || 9755);
const report = reporter();

let cdp;
try {
  cdp = await connectCdp({ port });

  // Set desktop viewport 1440x900
  await cdp.client.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  // Load login page first to check theme on login page
  await cdp.goto(`${base}/#/login`, 3000);
  const loginTheme = await cdp.evaluate(`JSON.stringify({
    url: window.location.href,
    hasLoginCard: !!document.querySelector('.login-card'),
    hasThemeCtl: !!document.querySelector('.themectl'),
    btnCount: document.querySelectorAll('.themectl__btn').length,
    activeTheme: document.documentElement.getAttribute('data-theme'),
    activeSetting: document.documentElement.getAttribute('data-theme-setting'),
    consoleErrors: window.__errors || []
  })`);
  const lt = JSON.parse(loginTheme);
  console.log('Login page inspection:', lt);
  report.check('登录页包含主题切换器', lt.hasThemeCtl, `buttons=${lt.btnCount}`);
  report.check('登录页初始主题生效', !!lt.activeTheme, `theme=${lt.activeTheme}`);

  // Auto login to enter shell
  await cdp.goto(`${base}/api/dev/auto-login`, 3000);
  await cdp.goto(`${base}/#/dashboard`, 3000);

  // 1. Check theme control in topbar
  const themeControl = await cdp.evaluate(`JSON.stringify({
    url: window.location.href,
    hasThemeCtl: !!document.querySelector('.themectl'),
    btnCount: document.querySelectorAll('.themectl__btn').length,
    activeTheme: document.documentElement.getAttribute('data-theme'),
    activeSetting: document.documentElement.getAttribute('data-theme-setting')
  })`);
  const tc = JSON.parse(themeControl);
  console.log('Dashboard inspection:', tc);
  report.check('顶部栏包含主题切换器', tc.hasThemeCtl, `按钮数=${tc.btnCount}`);
  report.check('初始主题生效', !!tc.activeTheme, `theme=${tc.activeTheme}, setting=${tc.activeSetting}`);

  // Test switching to light mode
  await cdp.evaluate(`document.querySelectorAll('.themectl__btn')[1].click()`);
  const lightState = await cdp.evaluate(`document.documentElement.getAttribute('data-theme')`);
  report.check('成功切换到 Light mode', lightState === 'light', `current=${lightState}`);

  // Test switching back to dark mode
  await cdp.evaluate(`document.querySelectorAll('.themectl__btn')[0].click()`);
  const darkState = await cdp.evaluate(`document.documentElement.getAttribute('data-theme')`);
  report.check('成功切换回 Dark mode', darkState === 'dark', `current=${darkState}`);

  // 2. Check sidebar collapse / expand
  const sidebarCheck = await cdp.evaluate(`JSON.stringify({
    hasCollapseBtn: !!document.querySelector('.sidebar__collapse-btn'),
    hasTopbarToggle: !!document.querySelector('.topbar__sidebar-toggle'),
    initialWidth: document.querySelector('.sidebar')?.getBoundingClientRect().width || 0,
    isCollapsed: document.querySelector('.shell')?.classList.contains('is-sidebar-collapsed') || false
  })`);
  const sc = JSON.parse(sidebarCheck);
  report.check('侧栏包含缩放折叠按钮', sc.hasCollapseBtn || sc.hasTopbarToggle, `w=${sc.initialWidth}`);

  // Click collapse toggle button in topbar
  await cdp.evaluate(`document.querySelector('.topbar__sidebar-toggle').click()`);
  const collapsedWidth = await cdp.evaluate(`document.querySelector('.sidebar').getBoundingClientRect().width`);
  const isCollapsedNow = await cdp.evaluate(`document.querySelector('.shell').classList.contains('is-sidebar-collapsed')`);
  report.check('侧栏成功折叠缩放到紧凑状态', isCollapsedNow && collapsedWidth < 100, `width=${collapsedWidth}px`);

  // Expand it back
  await cdp.evaluate(`document.querySelector('.topbar__sidebar-toggle').click()`);
  const expandedWidth = await cdp.evaluate(`document.querySelector('.sidebar').getBoundingClientRect().width`);
  report.check('侧栏成功展开恢复宽度', expandedWidth > 200, `width=${expandedWidth}px`);

  // 3. Check SIP Trunk Status page dropdown
  await cdp.goto(`${base}/#/siptrunk`, 3000);
  const siptrunkCheck = await cdp.evaluate(`JSON.stringify({
    hasDropdown: !!document.querySelector('.peer-dropdown'),
    hasTrigger: !!document.querySelector('.peer-dropdown__trigger'),
    triggerText: document.querySelector('.peer-dropdown__trigger span')?.textContent || '',
    hasNoOldSwitches: document.querySelectorAll('.u-card .u-switch').length === 0
  })`);
  const st = JSON.parse(siptrunkCheck);
  report.check('SIP Trunk 筛选呈现为下拉菜单', st.hasDropdown && st.hasTrigger, st.triggerText);
  report.check('旧的平铺开关已被移除', st.hasNoOldSwitches, 'no u-switch clutter');

  // Click to open dropdown menu
  await cdp.evaluate(`document.querySelector('.peer-dropdown__trigger').click()`);
  const menuCheck = await cdp.evaluate(`JSON.stringify({
    isOpen: document.querySelector('.peer-dropdown').classList.contains('is-open'),
    hasSearch: !!document.querySelector('.peer-dropdown__search'),
    hasList: !!document.querySelector('.peer-dropdown__list')
  })`);
  const mc = JSON.parse(menuCheck);
  report.check('点击触发器下拉菜单正常展开', mc.isOpen && mc.hasSearch && mc.hasList, 'menu opened');

  report.check('无 JS 控制台错误', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 2).join(' | '));
} catch (error) {
  console.error('异常:', error && error.message ? error.message : error);
  report.check('执行未抛异常', false, String((error && error.message) || error).slice(0, 160));
} finally {
  if (cdp) cdp.close();
  process.exit(report.summary() > 0 ? 1 : 0);
}
