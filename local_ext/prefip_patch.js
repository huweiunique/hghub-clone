/* CF 设置：复用上游设置区域；iOS 随包分发，普通网页只修正列表刷新。 */
(function () {
  'use strict';
  if (window.__hgPreferredIPInstalled) return;
  window.__hgPreferredIPInstalled = true;
  var bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.hgPreferredIP;
  var state = null;
  var busy = false;
  var requestID = 0;
  var dirty = false;
  var $ = function (id) { return document.getElementById(id); };

  function show(text) {
    if ($('prefIpInfo')) $('prefIpInfo').textContent = text;
  }

  function setBusy(value, text) {
    busy = value;
    ['btnRefreshPrefIp', 'hgPrefSave', 'hgPrefTest', 'hgPrefMode', 'hgPrefCustom', 'prefIpIsp'].forEach(function (id) {
      if ($(id)) $(id).disabled = value || !!(bridge && state && !state.supported);
    });
    if ($('hgPrefCancel')) $('hgPrefCancel').hidden = !value;
    if ($('btnRefreshPrefIp')) {
      $('btnRefreshPrefIp').textContent = value ? '处理中…' : (bridge ? '更新列表并测速' : '刷新自动列表');
      if (bridge && state && state.mode !== 'auto') $('btnRefreshPrefIp').disabled = true;
      if (bridge && dirty) $('btnRefreshPrefIp').disabled = true;
    }
    if ($('hgPrefTest') && bridge && dirty) $('hgPrefTest').disabled = true;
    if (text) show(text);
  }

  function display(result) {
    state = result;
    if ($('hgPrefSection')) $('hgPrefSection').hidden = !result.supported;
    window.HG_PREFIP = result.selectedIP || '';
    window.HG_PREFIP_LIST = (result.results || []).map(function (r) { return r.ip; });
    if ($('hgPrefMode')) $('hgPrefMode').value = result.mode;
    if ($('hgPrefCustom')) $('hgPrefCustom').value = (result.customIPs || []).join('\n');
    if ($('prefIpIsp')) $('prefIpIsp').value = result.isp || 'ct';
    draftVisibility();
    show(result.message || '普通连接');
    renderResults(result);
  }

  function renderResults(result) {
    var box = $('hgPrefResults');
    if (!box) return;
    box.replaceChildren();
    var progress = document.createElement('p');
    progress.className = 'hint';
    progress.textContent = result.running ? '测速进度：' + (result.completed || 0) + '/' + (result.total || 0)
      : '当前选择：' + (result.mode !== 'off' && result.selectedIP ? result.selectedIP : '普通连接');
    box.appendChild(progress);
    var results = (result.results || []).slice().sort(function (a, b) {
      return (a.state === 'ok' ? a.ms : Infinity) - (b.state === 'ok' ? b.ms : Infinity);
    });
    if (!results.length) return;
    var table = document.createElement('table');
    table.style.cssText = 'width:100%;table-layout:fixed;font-size:12px;border-collapse:collapse';
    var head = table.createTHead().insertRow();
    ['IP', '来源', '平均耗时 / 结果'].forEach(function (name, i) {
      var cell = document.createElement('th'); cell.textContent = name;
      cell.style.cssText = 'text-align:left;padding:6px 2px;width:' + [44, 22, 34][i] + '%';
      head.appendChild(cell);
    });
    var body = table.createTBody();
    var labels = {pending: '等待', testing: '测试中…', failed: '失败', cancelled: '已停止'};
    results.forEach(function (item) {
      var row = body.insertRow();
      var timing = item.state === 'ok' ? Number(item.ms).toFixed(1) + ' ms' : labels[item.state] || '未测试';
      if (result.mode !== 'off' && item.ip === result.selectedIP && item.state === 'ok') timing += ' · 已选';
      if (item.error) timing += '：' + item.error;
      [item.ip, item.source, timing].forEach(function (text) {
        var cell = row.insertCell(); cell.textContent = text;
        cell.style.cssText = 'padding:8px 2px;vertical-align:top;overflow-wrap:anywhere;border-top:1px solid var(--line)';
      });
    });
    box.appendChild(table);
  }

  function draftVisibility() {
    if (!$('hgPrefMode')) return;
    $('hgPrefCustomLabel').hidden = $('hgPrefMode').value === 'off';
    $('prefIpIsp').hidden = $('hgPrefMode').value !== 'auto';
  }

  async function nativeAction(body, pendingText) {
    if (busy) return;
    setBusy(true, pendingText);
    var generation = ++requestID;
    var reading = false;
    var poll = body.action !== 'status' ? setInterval(async function () {
      if (reading) return;
      reading = true;
      try {
        var progress = await bridge.postMessage({action: 'status'});
        if (busy && generation === requestID) { display(progress); setBusy(true); }
      } catch (error) { /* 主操作返回错误；进度读取失败不覆盖其最终回执。 */ }
      finally { reading = false; }
    }, 500) : null;
    try {
      var result = await bridge.postMessage(body);
      dirty = false;
      display(result);
    } catch (error) {
      show((error && error.message) || String(error));
    } finally { clearInterval(poll); ++requestID; setBusy(false); }
  }

  function mount() {
    var info = $('prefIpInfo');
    var refresh = $('btnRefreshPrefIp');
    if (!info || !refresh) return;
    info.setAttribute('role', 'status');
    info.setAttribute('aria-live', 'polite');
    refresh.textContent = '刷新自动列表';
    var explanation = refresh.parentElement.nextElementSibling;
    if (explanation) explanation.textContent = bridge
      ? '自动列表与自定义 IP 合并去重后一起测速；每个 IP 做 2 次独立 HTTPS 测试，按平均耗时选最快的可用 IP。自定义 IP 可填多条，每行一个，也可用逗号分隔。修改后请保存并测速。只测试后端连接，不测试视频 CDN；已有连接可能继续复用，完全切换可重新打开 App。'
      : '这里只获取第三方已测好的列表，不执行本机测速。普通浏览器不会通过这些 IP 连接；iOS 需安装支持优选的新 App。';
    refresh.onclick = function () {
      if (bridge) nativeAction({action: 'refresh'}, '正在更新自动列表并测速择优…');
      else window.loadPrefIp(true);
    };
    if ($('btnCopyPrefIp')) $('btnCopyPrefIp').onclick = function () {
      if (!window.HG_PREFIP) { show('暂无可复制的 IP'); return; }
      if (typeof window.copyText === 'function') window.copyText(window.HG_PREFIP);
    };
    if (!bridge) return;
    // 所有优选控件一起隐藏：不支持的系统看不到配置、按钮或说明，避免闪现。
    if (!$('hgPrefSection')) {
      var first = $('prefIpOn').parentElement.previousElementSibling;
      var section = document.createElement('div'); section.id = 'hgPrefSection'; section.hidden = true;
      first.insertAdjacentElement('beforebegin', section);
      var node = first;
      while (node) {
        var next = node.nextElementSibling;
        section.appendChild(node);
        if (node === explanation) break;
        node = next;
      }
    }
    if (!$('hgPrefMode')) {
      var enable = $('prefIpOn');
      if (enable) {
        enable.parentElement.hidden = true;
        if (enable.parentElement.previousElementSibling) enable.parentElement.previousElementSibling.textContent = 'CF 优选 IP';
      }
      var operator = $('prefIpIsp');
      var oldAuto = operator.querySelector('option[value="auto"]');
      if (oldAuto) oldAuto.remove();
      var controls = document.createElement('div');
      controls.id = 'hgPrefControls';
      controls.innerHTML = '<label class="hint" for="hgPrefMode">CF 优选方式</label>' +
        '<select id="hgPrefMode"><option value="off">关闭（普通连接）</option><option value="auto">开启（自动列表＋自定义 IP 一起测速）</option></select>' +
        '<label class="hint" id="hgPrefCustomLabel">自定义候选 IP（可选，每行一个）<textarea id="hgPrefCustom" rows="3" autocapitalize="off" autocomplete="off" spellcheck="false" placeholder="可添加多个 IPv4 / IPv6 地址" style="width:100%;box-sizing:border-box;min-height:88px;resize:vertical;background:var(--card2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px"></textarea></label>';
      operator.insertAdjacentElement('beforebegin', controls);
      var buttons = document.createElement('div');
      buttons.className = 'rowbtns';
      buttons.innerHTML = '<button class="btn ghost" id="hgPrefSave">保存并测速择优</button><button class="btn ghost" id="hgPrefTest">重新测速并选择</button><button class="btn ghost" id="hgPrefCancel" hidden>停止测速</button>';
      info.insertAdjacentElement('beforebegin', buttons);
      var results = document.createElement('div'); results.id = 'hgPrefResults';
      info.insertAdjacentElement('afterend', results);
      $('hgPrefMode').onchange = function () {
        dirty = true; draftVisibility(); setBusy(false); show('配置尚未保存，请点“保存并测速择优”');
      };
      operator.onchange = $('hgPrefCustom').oninput = function () {
        dirty = true; setBusy(false); show('配置尚未保存，请点“保存并测速择优”');
      };
      $('hgPrefSave').onclick = function () {
        nativeAction({action: 'save', mode: $('hgPrefMode').value,
                      isp: operator.value, customIPs: $('hgPrefCustom').value.trim()}, '正在保存候选并测速择优…');
      };
      $('hgPrefTest').onclick = function () {
        nativeAction({action: 'test'}, '正在测试所有候选 IP 并选择最快的…');
      };
      $('hgPrefCancel').onclick = async function () {
        $('hgPrefCancel').disabled = true;
        try { await bridge.postMessage({action: 'cancel'}); show('正在停止测速…'); }
        catch (error) { show('停止请求失败，请重试'); }
        finally { if ($('hgPrefCancel')) $('hgPrefCancel').disabled = false; }
      };
    }
  }

  // 上游 renderMe 每次都会调用此函数，因此重绘后重新绑定，无需轮询或全局 DOM 观察。
  window.loadPrefIp = async function (force) {
    mount();
    if (bridge) {
      if (state) display(state);
      if (busy) { setBusy(true); return; }
      return nativeAction({action: force ? 'refresh' : 'status'}, force ? '正在更新列表并测速…' : '正在读取本机优选配置…');
    }
    var id = ++requestID;
    setBusy(true, force ? '正在刷新自动列表…' : '正在获取自动列表…');
    var timer;
    try {
      var controller = new AbortController();
      timer = setTimeout(function () { controller.abort(); }, 12000);
      var isp = window.store ? window.store.get('hg_pref_isp', 'auto') : 'auto';
      var response = await fetch('/api/prefip?isp=' + encodeURIComponent(isp) + (force ? '&force=1' : ''),
                                 {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var json = await response.json();
      if (json.status === 0) throw new Error(json.msg || '获取失败');
      if (id !== requestID) return;
      var ips = (json.data && json.data.ips) || [];
      window.HG_PREFIP = ips[0] || ''; window.HG_PREFIP_LIST = ips;
      show(ips.length ? '列表 IP：' + ips[0] + '（共 ' + ips.length + ' 个；' + (force ? '已重新获取' : '获取完成') + '）'
                      : '列表为空，当前使用默认节点');
    } catch (error) {
      if (id === requestID) show('列表获取失败，请重试；本次未更新 IP');
    } finally {
      clearTimeout(timer);
      if (id === requestID) setBusy(false);
    }
  };
  if ($('prefIpInfo')) window.loadPrefIp();
})();
