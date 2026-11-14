"""看全集的真实浏览器布局回归；无 Chrome/Edge 时明确跳过，不访问上游。"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from shot import WS, find_chrome, free_port


class BrowserFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('HGHUB_UI_TESTS') != '1':
            raise unittest.SkipTest("未启用浏览器 UI 自动测试；使用 python tests/run_all.py --ui")
        try:
            chrome = find_chrome()
        except SystemExit:
            raise unittest.SkipTest("没有 Chrome/Edge，未运行播放器布局测试")
        (ROOT / ".test-tmp").mkdir(exist_ok=True)
        cls.profile = tempfile.TemporaryDirectory(dir=ROOT / ".test-tmp")
        cls.addClassCleanup(cls.profile.cleanup)
        port = free_port()
        args = [
            chrome, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
            # Linux 无头 runner 未必有鼠标。固定桌面输入能力，触屏用例另用
            # setTouchEmulationEnabled 覆盖；setEmulatedMedia 不支持 hover/pointer。
            "--blink-settings=availablePointerTypes=4,primaryPointerType=4,availableHoverTypes=2,primaryHoverType=2",
            f"--remote-debugging-port={port}", f"--user-data-dir={cls.profile.name}",
            "about:blank",
        ]
        # GitHub 托管 Linux runner 的用户命名空间限制会阻止 Chrome sandbox 启动。
        # 仅 CI 的隔离浏览器关闭 sandbox；测试页无外部脚本或真实用户数据。
        if sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS') == 'true':
            args.extend(['--no-sandbox', '--disable-dev-shm-usage'])
        cls.browser_log = open(Path(cls.profile.name) / 'chrome.log', 'wb')
        cls.addClassCleanup(cls.browser_log.close)
        cls.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=cls.browser_log)
        cls.addClassCleanup(cls.stop_browser)
        last_error = None
        for _ in range(300):
            if cls.proc.poll() is not None:
                raise RuntimeError('浏览器启动失败：' + (Path(cls.profile.name) / 'chrome.log').read_text(encoding='utf-8', errors='replace')[-4000:])
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as r:
                    pages = json.load(r)
                cls.ws = WS(next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page"))
                break
            except (OSError, StopIteration) as error:
                last_error = error
                time.sleep(0.1)
        else:
            log = (Path(cls.profile.name) / 'chrome.log').read_text(encoding='utf-8', errors='replace')[-4000:]
            raise RuntimeError(f"浏览器启动超时：{chrome}，{last_error!r}\n{log}")
        cls.ws.call("Page.enable")
        # 复用真实 HTML/CSS 和本地扩展，仅关闭联网业务脚本。
        html = re.sub(r"<script\b[^>]*>.*?</script>", "", (ROOT / "web/index.html").read_text(encoding="utf-8"), flags=re.S)
        frame = cls.ws.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
        cls.ws.call("Page.setDocumentContent", {"frameId": frame, "html": html})
        cls.evaluate("window.fetch = async () => ({status:200});")
        cls.evaluate((ROOT / "local_ext/web_patch.js").read_text(encoding="utf-8"))
        if getattr(cls, 'load_player_patch', True) and (ROOT / 'local_ext/player_patch.js').exists():
            cls.evaluate((ROOT / 'local_ext/player_patch.js').read_text(encoding='utf-8'))
            cls.evaluate((ROOT / 'local_ext/player_controls.js').read_text(encoding='utf-8'))
            cls.evaluate((ROOT / 'local_ext/video_enhance.js').read_text(encoding='utf-8'))
        cls.evaluate("document.body.classList.add('modal-open'); document.querySelector('#player').hidden=false; document.querySelector('#detailPane').hidden=true; document.querySelector('#playerPane').hidden=false;")
        cls.set_video_size(360, 640)

    @classmethod
    def set_video_size(cls, width, height):
        cls.evaluate("""(async () => {
          const c=document.createElement('canvas'); c.width=%d; c.height=%d;
          const v=document.querySelector('#video'); v.muted=true;
          if (v.srcObject) v.srcObject.getTracks().forEach(t=>t.stop());
          const ready=new Promise((resolve,reject)=>{v.onloadedmetadata=resolve; setTimeout(()=>reject(new Error('视频元数据超时')),3000);});
          v.srcObject=c.captureStream(1); c.getContext('2d').fillStyle='#6883ad';c.getContext('2d').fillRect(0,0,c.width,c.height);
          await ready; await v.play();
        })()""" % (width, height))

    @classmethod
    def stop_browser(cls):
        # 正常关闭可等待浏览器子进程释放 Windows profile 文件锁。
        try:
            cls.ws.send({"id": 99999, "method": "Browser.close"})
        except (OSError, AttributeError):
            cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # 仅终止本测试创建的浏览器进程树，不能误关用户的 Chrome。
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(cls.proc.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            else:
                cls.proc.kill()
            cls.proc.wait(timeout=10)
        if hasattr(cls, 'ws'):
            cls.ws.sock.close()
        cls.browser_log.close()
        for attempt in range(20):
            try:
                cls.profile.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)

    @classmethod
    def evaluate(cls, expression):
        r = cls.ws.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in r:
            raise AssertionError(r["exceptionDetails"])
        return r["result"].get("value")

class PlayerLayoutTests(BrowserFixture):
    def measure(self, width, height):
        self.ws.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": True})
        return self.evaluate("""(async () => {
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          const rect = s => {const r=document.querySelector(s).getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom};};
          return {video:rect('#video'),controls:rect('#playerPane .ctl'),nav:rect('.bottomnav'),back:rect('#btnBackDetail'),
            buttons:[...document.querySelectorAll('#playerPane .ctl button,#playerPane .ctl select')].map(b=>{const r=b.getBoundingClientRect();return {x:r.x,right:r.right,bottom:r.bottom};}),
            viewport:innerWidth,fit:getComputedStyle(document.querySelector('#video')).objectFit,overflow:document.documentElement.scrollWidth>innerWidth};
        })()""")

    def test_player_uses_available_height_and_keeps_controls_visible(self):
        for width, height in [(375, 667), (430, 932), (932, 430), (768, 1024), (1024, 1366), (1440, 1000)]:
            with self.subTest(viewport=(width, height)):
                m = self.measure(width, height)
                v, ctl = m["video"], m["controls"]
                self.assertEqual(v["h"], height, m)
                self.assertEqual(v["w"], width, m)
                self.assertEqual(m["nav"]["h"], 0, m)
                self.assertLessEqual(ctl["bottom"], height, m)
                self.assertFalse(m["overflow"], m)
                self.assertEqual(m["viewport"], width, m)
                self.assertEqual(m["fit"], "contain")
                for b in m["buttons"]:
                    self.assertGreaterEqual(b["x"], 0, m)
                    self.assertLessEqual(b["right"], width, m)
                    self.assertLessEqual(b["bottom"], height, m)

    def test_immersive_player_uses_unified_controls_and_fills_viewport(self):
        self.measure(430, 932)
        result = self.evaluate("""({nav:getComputedStyle(document.querySelector('.bottomnav')).display,
          width:document.querySelector('#video').getBoundingClientRect().width,
          height:document.querySelector('#video').getBoundingClientRect().height,
          controls:document.querySelector('#video').controls,
          rotate:!!document.querySelector('#hgRotate')})""")
        self.assertEqual(result['nav'], 'none', result)
        self.assertEqual(result['width'], 430, result)
        self.assertEqual(result['height'], 932, result)
        self.assertFalse(result['controls'], result)
        self.assertTrue(self.evaluate("!!document.querySelector('#hgSystemFullscreen')"))
        self.assertTrue(result['rotate'], result)

    def test_search_header_has_no_gap_above_scrolled_content(self):
        self.evaluate("document.querySelector('#player').hidden=true;document.body.classList.remove('modal-open')")
        try:
            self.measure(375, 667)
            self.assertEqual(self.evaluate("document.querySelector('header').getBoundingClientRect().top"), 0)
        finally:
            self.evaluate("document.querySelector('#player').hidden=false;document.body.classList.add('modal-open')")

    def test_rotation_is_manual_and_resets_when_returning_to_detail(self):
        self.measure(430, 932)
        self.evaluate("document.querySelector('#hgRotate').click()")
        rotated = self.evaluate("""(() => {
          const r=document.querySelector('#video').getBoundingClientRect();
          return {x:r.x,y:r.y,w:r.width,h:r.height,landscape:document.body.classList.contains('hg-landscape'),
            logicalWidth:document.querySelector('#video').clientWidth};
        })()""")
        self.assertEqual(rotated, {'x': 0, 'y': 0, 'w': 430, 'h': 932, 'landscape': True, 'logicalWidth': 932})
        self.measure(932, 430)
        self.assertTrue(self.evaluate("document.body.classList.contains('hg-landscape')"))
        self.evaluate("document.querySelector('#playerPane').hidden=true; document.querySelector('#detailPane').hidden=false")
        self.measure(430, 932)
        self.assertFalse(self.evaluate("document.body.classList.contains('hg-landscape')"))
        self.assertGreater(self.evaluate("document.querySelector('.bottomnav').getBoundingClientRect().height"), 0)
        self.evaluate("document.querySelector('#playerPane').hidden=false;document.querySelector('#detailPane').hidden=true")

    def test_playing_controls_hide_and_reappear_with_explicit_system_fullscreen(self):
        self.evaluate("document.querySelector('#video').dispatchEvent(new Event('play'))")
        self.assertFalse(self.evaluate("document.querySelector('#video').controls"))
        hidden = self.evaluate("""(async()=>{
          await new Promise(r=>setTimeout(r,4200));
          return getComputedStyle(document.querySelector('#btnBackDetail')).visibility;
        })()""")
        self.assertEqual(hidden, 'hidden')
        self.evaluate("document.querySelector('#playerPane').dispatchEvent(new Event('pointerdown'))")
        self.assertEqual(self.evaluate("getComputedStyle(document.querySelector('#btnBackDetail')).visibility"), 'visible')

    def test_app_settings_survives_me_rerender_and_opens_native_config(self):
        script = (ROOT / 'local_ext/app_settings.js').read_text(encoding='utf-8')
        original = self.evaluate("document.querySelector('#meBox').innerHTML")
        self.evaluate("""
          window.HGAppConfig={address:'https://example.test/'+'a'.repeat(140)+'?x=<img>',hasKey:true,versionDescription:'1.2.0.8-N261113-9478076'};
          window.__settingsMessages=[];
          window.webkit={messageHandlers:{hgSettings:{postMessage:m=>window.__settingsMessages.push(m)}}};
          document.querySelector('#meBox').innerHTML='<div class="mebox"><h3>设置</h3><label>播放线路</label><select id="lineSel"><option value="direct">直连 CDN</option><option value="proxy" selected>8080 代理</option></select></div>';
        """)
        self.evaluate(script)
        try:
            for has_key in [True, False]:
                self.evaluate("window.HGAppConfig.hasKey=" + json.dumps(has_key))
                # 模拟登录、收藏、历史操作导致 renderMe 完整重绘。
                self.evaluate("document.querySelector('#meBox').innerHTML='<div class=\"mebox\"><h3>设置</h3><label>播放线路</label><select id=\"lineSel\"><option value=\"direct\">直连 CDN</option><option value=\"proxy\" selected>8080 代理</option></select></div>'")
                result = self.evaluate("""(async()=>{
                  await new Promise(r=>setTimeout(r,0));
                  const section=document.querySelector('#__hg_app_settings');
                  section.querySelector('button').click();
                  return {count:document.querySelectorAll('#__hg_app_settings').length,
                    text:section.textContent,images:section.querySelectorAll('img').length,
                    options:[...document.querySelector('#lineSel').options].map(o=>o.value),
                    selected:document.querySelector('#lineSel').value,
                    collapsed:!document.querySelector('#__hg_playback_fallback').open,
                    configFirst:!!(section.compareDocumentPosition(document.querySelector('#__hg_playback_fallback')) & Node.DOCUMENT_POSITION_FOLLOWING),
                    inside:section.closest('.mebox').contains(document.querySelector('#lineSel')),
                    messages:window.__settingsMessages};
                })()""")
                self.assertEqual(result['count'], 1, result)
                self.assertEqual(result['images'], 0, result)
                self.assertEqual(result['options'], ['direct', 'proxy'], result)
                self.assertEqual(result['selected'], 'proxy', result)
                self.assertTrue(result['collapsed'], result)
                self.assertTrue(result['configFirst'], result)
                self.assertTrue(result['inside'], result)
                self.assertEqual(result['messages'][-1], 'open', result)
                self.assertIn('版本：1.2.0.8-N261113-9478076', result['text'])
                self.assertIn('已配置' if has_key else '未配置（可选）', result['text'])
            self.evaluate("document.querySelector('#lineSel').value='direct'; document.querySelector('#lineSel').dispatchEvent(new Event('change'))")
            self.assertIn('直连 CDN', self.evaluate("document.querySelector('#__hg_playback_fallback summary').textContent"))
            self.evaluate("document.body.insertAdjacentHTML('beforeend','<div id=\"__hg_key_box\"><div></div></div>')")
            recovery = self.evaluate("""(async()=>{
              await new Promise(r=>setTimeout(r,0));
              const button=document.querySelector('#__hg_key_box [data-hg-settings]');
              button.click();
              return {count:document.querySelectorAll('#__hg_key_box [data-hg-settings]').length,
                message:window.__settingsMessages.at(-1)};
            })()""")
            self.assertEqual(recovery, {'count': 1, 'message': 'open'})
        finally:
            self.evaluate("document.querySelector('#__hg_key_box')?.remove()")
            self.evaluate("delete window.HGAppConfig; delete window.webkit; document.querySelector('#meBox').innerHTML=" + json.dumps(original))

    def test_larger_screen_and_nav_resize_change_player_space(self):
        small = self.measure(375, 667)["video"]
        large = self.measure(1024, 1366)["video"]
        self.assertGreater(large["w"], small["w"] * 2)
        self.assertGreater(large["h"], small["h"] * 1.5)
        self.evaluate("document.querySelector('.bottomnav').style.paddingBottom='60px'")
        try:
            resized = self.measure(1024, 1366)
            self.assertEqual(resized["video"]["h"], large["h"], resized)
            self.assertLessEqual(resized["controls"]["bottom"], 1366)
        finally:
            self.evaluate("document.querySelector('.bottomnav').style.paddingBottom=''")

    def test_landscape_source_and_detail_return(self):
        self.set_video_size(640, 360)
        try:
            m = self.measure(932, 430)
            self.assertGreater(m["video"]["w"], 900)
            self.assertEqual(m["video"]["bottom"], 430)
            self.assertLessEqual(m["controls"]["bottom"], 430)
            self.evaluate("document.querySelector('#playerPane').hidden=true; document.querySelector('#detailPane').hidden=false")
            self.measure(1024, 1366)
            detail = self.evaluate("({hidden:getComputedStyle(document.querySelector('#playerPane')).display, max:getComputedStyle(document.querySelector('#player .box')).maxWidth, overflow:getComputedStyle(document.querySelector('#player')).overflowY})")
            self.assertEqual(detail, {"hidden": "none", "max": "900px", "overflow": "auto"})
        finally:
            self.evaluate("document.querySelector('#playerPane').hidden=false; document.querySelector('#detailPane').hidden=true")
            self.set_video_size(360, 640)

    def test_page_layouts_small_screen_safe_area_and_long_text(self):
        targets = ['feed', 'catGrid', 'rankList', 'postList', 'meBox', 'searchGrid', 'pDesc', 'pEps']
        saved = self.evaluate("Object.fromEntries(" + json.dumps(targets) + ".map(id=>[id,document.getElementById(id).innerHTML]))")
        self.evaluate("""(() => {
          const text='SpecialEpisode2026'.repeat(8);
          const card='<div class="card"><img><div class="t"><h4>'+text+'</h4><p>'+text+'</p></div></div>';
          document.querySelector('#feed').innerHTML='<div class="slide"><div class="info"><h3>示例短剧</h3><button class="watchall">看全集</button></div></div>';
          for(const id of ['catGrid','searchGrid']) document.getElementById(id).innerHTML=card.repeat(8);
          document.querySelector('#rankList').innerHTML=('<div class="rankrow"><span class="no">1</span><img><div><h4>'+text+'</h4><p>'+text+'</p></div></div>').repeat(8);
          document.querySelector('#postList').innerHTML='<div class="post"><h4>'+text+'</h4><p>'+text+'</p></div>';
          document.querySelector('#meBox').innerHTML='<div class="mebox"><h3>登录 / 注册</h3><input placeholder="用户名"><input placeholder="密码"><button class="btn">登录</button></div>';
          document.querySelector('#pDesc').textContent=text.repeat(8);
          document.querySelector('#pEps').innerHTML='<button>第1集</button>'.repeat(100);
          document.body.classList.add('hg-app'); document.body.classList.remove('modal-open');
          document.querySelector('#player').hidden=true;
        })()""")
        try:
            for width, height in [(320,568),(375,667),(430,932),(932,430),(1024,1366),(1440,1000)]:
                for view in ['home','cat','rank','posts','me','search']:
                    with self.subTest(viewport=(width,height), view=view):
                        self.evaluate("document.querySelectorAll('main>section').forEach(s=>s.hidden=s.id!==" + json.dumps('view-'+view) + "); document.querySelector('.bottomnav').style.paddingBottom='40px'")
                        self.measure(width,height)
                        m = self.evaluate("""(() => {
                          const nav=document.querySelector('.bottomnav').getBoundingClientRect();
                          const search=document.querySelector('#btnSearch').getBoundingClientRect();
                          return {vw:innerWidth,sw:document.documentElement.scrollWidth,searchRight:search.right,
                            feedBottom:document.querySelector('#feed').getBoundingClientRect().bottom,navTop:nav.top};
                        })()""")
                        self.assertEqual(m['vw'],width,m)
                        self.assertLessEqual(m['sw'],width,m)
                        self.assertLessEqual(m['searchRight'],width-12+1,m)
                        if view=='home':
                            self.assertLessEqual(m['feedBottom'],m['navTop']+1,m)
                            self.assertGreater(m['feedBottom'],m['navTop']-2,m)
                # 详情、评论和分享弹层滚到底后，最后的操作必须在导航上方。
                self.evaluate("document.querySelector('#player').hidden=false;document.querySelector('#playerPane').hidden=true;document.querySelector('#detailPane').hidden=false;document.body.classList.add('modal-open')")
                for selector,last in [('#player','#pEps button:last-child'),('#commentSheet','.commentbar'),('#shareSheet','#btnDownloadApp')]:
                    self.evaluate("document.querySelector("+json.dumps(selector)+").hidden=false")
                    self.measure(width,height)
                    m=self.evaluate("""(() => {
                      const panel=document.querySelector(%s);panel.scrollTop=panel.scrollHeight;
                      const last=document.querySelector(%s).getBoundingClientRect();
                      return {bottom:last.bottom,navTop:document.querySelector('.bottomnav').getBoundingClientRect().top,
                        iconMax:Math.max(0,...[...panel.querySelectorAll('.btn svg')].map(s=>s.getBoundingClientRect().height)),width:innerWidth};
                    })()""" % (json.dumps(selector),json.dumps(last)))
                    self.assertLessEqual(m['bottom'],m['navTop']+1,m)
                    self.assertLessEqual(m['iconMax'],14,m)
                    self.assertEqual(m['width'],width,m)
                    self.evaluate("document.querySelector("+json.dumps(selector)+").hidden=true")
        finally:
            self.evaluate("Object.entries("+json.dumps(saved)+").forEach(([id,html])=>document.getElementById(id).innerHTML=html)")
            self.evaluate("document.body.classList.remove('hg-app');document.body.classList.add('modal-open');document.querySelector('.bottomnav').style.paddingBottom='';document.querySelectorAll('main>section').forEach(s=>s.hidden=s.id!=='view-home');document.querySelector('#player').hidden=false;document.querySelector('#playerPane').hidden=false;document.querySelector('#detailPane').hidden=true;document.querySelectorAll('.sheet').forEach(s=>s.hidden=true)")

    def test_key_dialog_can_scroll_on_short_viewport(self):
        # about:blank 没有可用存储源；仅替代存储和鉴权回执，执行真实弹窗代码。
        self.evaluate("Object.defineProperty(window,'localStorage',{configurable:true,value:{setItem(){},removeItem(){}}}); window.fetch=async()=>({status:401})")
        self.evaluate((ROOT / 'local_ext/web_patch.js').read_text(encoding='utf-8'))
        try:
            self.measure(568,240)
            m=self.evaluate("""(() => {
              const box=document.querySelector('#__hg_key_box');
              const top=box.firstElementChild.getBoundingClientRect().top;
              box.scrollTop=box.scrollHeight;
              return {top:top,bottom:document.querySelector('#__hg_key_go').getBoundingClientRect().bottom,h:innerHeight};
            })()""")
            self.assertGreaterEqual(m['top'],0,m)
            self.assertLessEqual(m['bottom'],m['h'],m)
        finally:
            self.evaluate("document.querySelector('#__hg_key_box')?.remove();window.fetch=async()=>({status:200})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
