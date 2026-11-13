/* HGhub 本地扩展：访问密钥（前端部分）
 *
 * 由 tools/apply_local_patches.py 在 web/index.html 里以一行
 *   <script src="/local_ext/web_patch.js"></script>
 * 引入，不修改页面正文，上游更新时不会冲突。
 *
 * 做两件事：
 *   1. 后端启用了 HGHUB_ACCESS_KEY 时，探测到 401 就弹输入框；
 *      输入正确后后端下发 Cookie，之后所有 /api/*、/proxy/* 自动带上。
 *   2. 用 ?key=xxx 打开时不需要弹框（后端已 302 并写好 Cookie）。
 */
(function () {
  'use strict';

  function boot() {
    installStyles();
    probe();
  }

  /** App 壳（WKWebView/Android WebView）里 UA 不含 Safari 字样，用来加仅壳内生效的样式 */
  function isAppShell() {
    try {
      if (/[?&]app=1\b/.test(location.search)) return true;
      var ua = navigator.userAgent || '';
      return /iPhone|iPad|iPod/.test(ua) && !/Safari\//.test(ua);
    } catch (e) { return false; }
  }

  /** 只往页面里追加 <style>，不修改上游正文；网页端和 App 壳表现各自正确 */
  function installStyles() {
    if (document.getElementById('__hg_style')) return;
    if (isAppShell()) document.body.classList.add('hg-app');
    var st = document.createElement('style');
    st.id = '__hg_style';
    st.textContent = [
      /* 行内图标：.ic-svg 默认 display:block，会把简介/统计里的 ★ 挤到单独一行 */
      '.meta .ic-svg,.detail-stats .ic-svg,.card .t p .ic-svg,',
      '.rankrow p .ic-svg,.post .meta .ic-svg{display:inline-block;vertical-align:-2px}',
      /* App 壳右上角的齿轮浮层会压住“搜索”按钮，给顶栏右侧留出空间 */
      'body.hg-app header{padding-right:78px}'
    ].join('');
    document.head.appendChild(st);
  }

  /** 从页面 URL 里取 ?key= 参数（App 壳/分享链接可能带） */
  function keyFromURL() {
    try {
      return new URLSearchParams(location.search).get('key') || '';
    } catch (e) { return ''; }
  }

  /**
   * 用 ?key= 换 Cookie。
   * 关键：App 壳（尤其 WKWebView）跟随 302 时可能没把 Set-Cookie 落进页面容器，
   * 所以这里主动发一次请求，让浏览器/WebView 自己处理 Set-Cookie，
   * 而不是依赖壳的跳转行为。
   */
  async function exchangeKey(key) {
    if (!key) return false;
    try {
      // 先验证 key 对错（带 key 请求受保护接口，200 即正确）
      var probe = await fetch('/api/site/categories/video?key=' + encodeURIComponent(key),
        { headers: { 'Accept': 'application/json' }, cache: 'no-store' });
      if (probe.status === 401) return false;
      // 再走首页换 Cookie（credentials 必须带上，否则 Set-Cookie 被忽略）
      await fetch('/?key=' + encodeURIComponent(key), { credentials: 'same-origin', cache: 'no-store' });
      localStorage.removeItem('hg_need_key');
      return true;
    } catch (e) {
      return false;
    }
  }

  /** 去掉地址栏里的 key，避免留在历史记录/Referer */
  function stripKey() {
    try {
      var u = new URL(location.href);
      u.searchParams.delete('key');
      history.replaceState(null, '', u.pathname + (u.search ? u.search : '') + u.hash);
    } catch (e) {}
  }

  async function probe() {
    // 1) URL 里带了 key（App 壳注入的）：先换 Cookie，换成功就不用弹窗
    var urlKey = keyFromURL();
    if (urlKey && await exchangeKey(urlKey)) {
      stripKey();
      return;
    }

    // 2) 无论本地标记如何，都实测一次：Cookie 可能已经由上次登录/App 壳写好。
    //    以前 hg_need_key 一旦残留就会无条件弹框，造成“App 里配置过密钥，
    //    进页面还要再输一次”。现在以服务端实际返回为准。
    try {
      var r = await fetch('/api/site/categories/video', {
        headers: { 'Accept': 'application/json' }, cache: 'no-store'
      });
      if (r.status !== 401) {                   // 没开密钥 / Cookie 仍然有效
        localStorage.removeItem('hg_need_key');
        return;
      }
      localStorage.setItem('hg_need_key', '1');
    } catch (e) {
      return;                                   // 网络问题，别打扰用户
    }
    askKey();
  }

  function askKey() {
    if (document.getElementById('__hg_key_box')) return;
    var wrap = document.createElement('div');
    wrap.id = '__hg_key_box';
    wrap.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.85);' +
      'display:flex;align-items:center;justify-content:center;padding:24px;' +
      '-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)';
    wrap.innerHTML =
      '<div style="background:var(--card,#1a1a1f);color:var(--text,#f5f5f5);border-radius:18px;' +
      'padding:22px;max-width:360px;width:100%;box-shadow:0 12px 40px rgba(0,0,0,.5)">' +
      '<h3 style="margin:0 0 8px;font-size:17px">需要访问密钥</h3>' +
      '<p style="margin:0 0 12px;font-size:13px;color:var(--muted,#9a9aa3);line-height:1.5">' +
      '这台服务器开启了访问密钥，输入一次即可（保存在本机，30 天有效）</p>' +
      '<input id="__hg_key_input" type="password" autocomplete="off" placeholder="粘贴访问密钥" ' +
      'style="width:100%;padding:12px;border-radius:10px;border:1px solid var(--line,#2a2a32);' +
      'background:var(--card2,#22222a);color:inherit;font-size:15px">' +
      '<p id="__hg_key_err" style="color:#ff2d55;font-size:13px;margin:8px 0 0;display:none">密钥不正确</p>' +
      '<button id="__hg_key_go" style="width:100%;margin-top:14px;padding:12px;border:0;border-radius:12px;' +
      'background:#ff2d55;color:#fff;font-size:15px;font-weight:600">进入</button>' +
      '<p style="margin:12px 0 0;font-size:12px;color:var(--muted,#9a9aa3)">也可以直接用带 ?key= 的链接打开</p>' +
      '</div>';
    document.body.appendChild(wrap);

    var input = wrap.querySelector('#__hg_key_input');
    var err = wrap.querySelector('#__hg_key_err');
    var btn = wrap.querySelector('#__hg_key_go');
    input.focus();

    async function submit() {
      var key = input.value.trim();
      if (!key) return;
      btn.disabled = true;
      try {
        if (!await exchangeKey(key)) {
          err.style.display = 'block';
          btn.disabled = false;
          return;
        }
        wrap.remove();
        location.reload();
      } catch (e) {
        err.textContent = '网络错误：' + e;
        err.style.display = 'block';
        btn.disabled = false;
      }
    }
    btn.onclick = submit;
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
