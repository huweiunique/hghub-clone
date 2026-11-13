/* iOS 随包注入的设置入口，原版服务器无需安装本地扩展。 */
(function () {
  'use strict';
  /** 只在 App 提供原生配置桥时增加入口；renderMe 重绘后自动恢复。 */
  function installAppSettings() {
    var config = window.HGAppConfig;
    var bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.hgSettings;
    var box = document.getElementById('meBox');
    if (!config || !bridge || !box) return;
    var style = document.createElement('style');
    style.textContent = 'body.hg-app header{padding-right:12px}#__hg_app_settings{border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:16px}#__hg_app_settings p{overflow-wrap:anywhere}#__hg_app_settings button,#__hg_playback_fallback summary{min-height:44px}#__hg_playback_fallback{margin-bottom:16px}#__hg_playback_fallback summary{cursor:pointer;padding:10px 0}';
    document.head.appendChild(style);
    function openButton() {
      var button = document.createElement('button');
      button.className = 'btn ghost';
      button.textContent = '配置后端地址与密钥';
      button.style.minHeight = '44px';
      button.onclick = function () { bridge.postMessage('open'); };
      return button;
    }
    function mount() {
      if (window.HGAppConfig !== config) return;
      // 密钥错误时，弹窗会挡住“我的”，仍须允许用户切换其他服务。
      var keyBox = document.querySelector('#__hg_key_box > div');
      if (keyBox && !keyBox.querySelector('[data-hg-settings]')) {
        var recovery = openButton();
        recovery.setAttribute('data-hg-settings', '');
        recovery.style.marginTop = '12px';
        keyBox.appendChild(recovery);
      }
      var line = box.querySelector('#lineSel');
      var settings = line && line.closest('.mebox');
      if (!settings) return;
      // 这两项共用当前后端，不是两台独立的备用服务器。保留原 select 与事件。
      if (!settings.querySelector('#__hg_playback_fallback')) {
        var directOption = line.querySelector('option[value="direct"]');
        var proxyOption = line.querySelector('option[value="proxy"]');
        if (directOption) directOption.textContent = '直连 CDN（优先）';
        if (proxyOption) proxyOption.textContent = '后端代取清单（备用）';
        var fallback = document.createElement('details');
        fallback.id = '__hg_playback_fallback';
        var summary = document.createElement('summary');
        function updateSummary() {
          summary.textContent = '播放方式 · 当前：' + (line.value === 'direct' ? '直连 CDN' : '后端代取清单');
        }
        updateSummary();
        line.addEventListener('change', updateSummary);
        var hint = settings.querySelector('#__hg_playback_help') || document.createElement('p');
        hint.id = '__hg_playback_help';
        hint.className = 'hint';
        hint.textContent = '两种方式都使用已配置的后端地址和密钥获取列表、搜索结果和播放地址。直连 CDN：手机直接获取播放清单和视频。后端代取清单：由同一后端获取播放清单，视频分片仍可能由手机直接访问 CDN。';
        var label = line.previousElementSibling;
        settings.insertBefore(fallback, label || line);
        fallback.appendChild(summary);
        if (label && label.tagName === 'LABEL') fallback.appendChild(label);
        fallback.append(line, hint);
      }
      if (box.querySelector('#__hg_app_settings')) return;
      var section = document.createElement('div');
      section.id = '__hg_app_settings';
      var title = document.createElement('p');
      title.textContent = '后端地址与访问密钥';
      var address = document.createElement('p');
      address.className = 'hint';
      address.textContent = config.address || '尚未配置地址';
      var key = document.createElement('p');
      key.className = 'hint';
      key.textContent = '访问密钥：' + (config.hasKey ? '已配置' : '未配置（可选）');
      var note = document.createElement('p');
      note.className = 'hint';
      note.textContent = '下方两种播放方式共用此后端，无需配置其他服务器地址。密钥仅用于后端鉴权，不会发送给视频 CDN。';
      section.append(title, address, key, note, openButton());
      settings.insertBefore(section, settings.querySelector('#__hg_playback_fallback'));
    }
    mount();
    new MutationObserver(mount).observe(document.body, { childList: true, subtree: true });
  }

  installAppSettings();
})();
