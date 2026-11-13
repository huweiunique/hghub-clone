"""离线验证刷新缓存、错误回执和实际设置事件；不冒充 iOS 原生连接测试。"""
import importlib.util
import io
import json
import re
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from test_player_layout import BrowserFixture, ROOT

_spec = importlib.util.spec_from_file_location('web_prefip_fixture', ROOT / 'web/server.py')
web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web)
from local_ext import preferred_ip


class PreferredIPServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        preferred_ip._CACHE.clear()

    def get(self, suffix):
        try:
            response = urllib.request.urlopen(self.base + '/api/prefip' + suffix, timeout=2)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def test_force_refresh_reaches_source_and_returns_new_ip(self):
        with patch.object(preferred_ip, 'fetch_list', side_effect=[['192.0.2.1'], ['192.0.2.2']]) as fetch:
            self.assertEqual(self.get('?isp=ct')[1]['data']['ips'], ['192.0.2.1'])
            self.assertTrue(self.get('?isp=ct')[1]['data']['cached'])
            code, result, headers = self.get('?isp=ct&force=1')
            self.assertEqual((code, result['data']['ips']), (200, ['192.0.2.2']))
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(fetch.call_count, 2)

    def test_failed_force_refresh_is_visible_and_preserves_good_cache(self):
        with patch.object(preferred_ip, 'fetch_list', side_effect=[['192.0.2.1'], OSError('fixture')]):
            self.get('?isp=cu')
            self.assertEqual(self.get('?isp=cu&force=1')[0], 502)
            self.assertEqual(self.get('?isp=cu')[1]['data']['ips'], ['192.0.2.1'])

    def test_source_parser_accepts_ipv4_ipv6_deduplicates_and_rejects_invalid(self):
        text = '192.0.2.1#测试,2001:db8::1#测试\n999.1.2.3#无效\n192.0.2.1#重复\n<html>错误页</html>'
        with patch.object(preferred_ip.urllib.request, 'urlopen', return_value=io.BytesIO(text.encode())):
            self.assertEqual(preferred_ip.fetch_list('ct'), ['192.0.2.1', '2001:db8::1'])


class PreferredIPBrowserTests(BrowserFixture):
    load_player_patch = False

    @classmethod
    def set_video_size(cls, width, height):
        # 本用例只检查设置，不启动媒体流。
        pass

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.evaluate("""
          const values={};
          Object.defineProperty(window,'localStorage',{configurable:true,value:{
            getItem:k=>values[k]??null,setItem:(k,v)=>values[k]=String(v),clear:()=>Object.keys(values).forEach(k=>delete values[k])}});
          window.fetch=async()=>({ok:true,json:async()=>({data:{items:[],ips:[]}})});
        """)
        html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
        main = next(s for s in re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S) if 'var UP =' in s)
        cls.evaluate(main.replace('loadHotTags();\nloadHome();\nhandleDeepLink();', ''))

    def setUp(self):
        self.evaluate("""
          localStorage.clear();window.__hgPreferredIPInstalled=false;delete window.webkit;
          window.loadPrefIp=async()=>{};
          window.requests=[];
          window.fetch=async url=>{requests.push(String(url));return {ok:true,json:async()=>({status:1,data:{ips:['192.0.2.1']}})}};
          renderMe();
        """)

    def install(self):
        self.evaluate((ROOT / 'local_ext/prefip_patch.js').read_text(encoding='utf-8'))

    def test_refresh_click_has_pending_feedback_and_force_flag(self):
        self.install()
        self.evaluate("window.fetch=url=>{requests.push(url);return new Promise(r=>window.finishPref=r)};document.querySelector('#btnRefreshPrefIp').click()")
        self.assertTrue(self.evaluate("document.querySelector('#btnRefreshPrefIp').disabled"))
        self.assertIn('正在刷新', self.evaluate("document.querySelector('#prefIpInfo').textContent"))
        self.assertIn('force=1', self.evaluate('requests.at(-1)'))
        self.evaluate("finishPref({ok:true,json:async()=>({status:1,data:{ips:['192.0.2.2']}})});Promise.resolve()")
        self.assertEqual(self.evaluate('window.HG_PREFIP'), '192.0.2.2')

    def test_native_save_and_test_use_device_bridge_instead_of_web_api(self):
        self.evaluate(r"""
          window.nativeCalls=[];
          window.nativeState={supported:true,mode:'auto',isp:'ct',customIPs:[],selectedIP:'192.0.2.1',message:'已启用',results:[]};
          window.webkit={messageHandlers:{hgPreferredIP:{postMessage:async body=>{
            nativeCalls.push(body);
            if(body.action==='save')Object.assign(nativeState,body,{customIPs:body.customIPs.split(/[,\n]/).filter(Boolean)});
            return {...nativeState};
          }}}};
        """)
        self.install()
        self.evaluate("document.querySelector('#hgPrefCustom').value='2001:db8::2,192.0.2.3';document.querySelector('#hgPrefSave').click();Promise.resolve()")
        call = self.evaluate('nativeCalls.at(-1)')
        self.assertEqual((call['action'], call['mode'], call['customIPs']), ('save', 'auto', '2001:db8::2,192.0.2.3'))
        self.evaluate("document.querySelector('#hgPrefTest').click();Promise.resolve()")
        self.assertEqual(self.evaluate('nativeCalls.at(-1).action'), 'test')
        self.evaluate('renderMe();Promise.resolve()')
        self.assertEqual(self.evaluate("document.querySelector('#hgPrefMode').value"), 'auto')
        self.assertEqual(self.evaluate("document.querySelector('#hgPrefCustom').value"), '2001:db8::2\n192.0.2.3')
        self.assertEqual(self.evaluate("document.querySelectorAll('#hgPrefControls').length"), 1)

    def test_ios16_entire_section_is_hidden_including_explanation_and_after_rerender(self):
        self.evaluate("window.webkit={messageHandlers:{hgPreferredIP:{postMessage:async()=>({supported:false,mode:'auto',isp:'ct',message:'iOS 16 使用普通连接'})}}}")
        self.install()
        for _ in range(2):
            self.assertTrue(self.evaluate("document.querySelector('#hgPrefSection').hidden"))
            for selector in ['#hgPrefMode', '#hgPrefSave', '#prefIpInfo', '#btnRefreshPrefIp']:
                self.assertEqual(self.evaluate(f"document.querySelector('{selector}').getBoundingClientRect().height"), 0)
            self.evaluate('renderMe();Promise.resolve()')

    def test_results_show_fastest_choice_failures_and_average_timings(self):
        self.evaluate("""
          window.webkit={messageHandlers:{hgPreferredIP:{postMessage:async()=>({supported:true,mode:'auto',isp:'ct',customIPs:[],
            selectedIP:'192.0.2.2',message:'测速完成',results:[
              {ip:'192.0.2.1',source:'自动',state:'ok',ms:250},
              {ip:'192.0.2.2',source:'自定义',state:'ok',ms:80},
              {ip:'192.0.2.3',source:'自动',state:'failed',error:'超时'}]})}}};
        """)
        self.install()
        rows = self.evaluate("[...document.querySelectorAll('#hgPrefResults tbody tr')].map(r=>r.textContent)")
        self.assertIn('192.0.2.2', rows[0])
        self.assertIn('80.0 ms · 已选', rows[0])
        self.assertIn('失败：超时', rows[-1])
        self.assertEqual(self.evaluate('window.HG_PREFIP_LIST.length'), 3)

    def test_pending_native_run_shows_progress_and_can_be_cancelled(self):
        self.evaluate("""
          window.nativeCalls=[];
          window.fixtureRunning=false;
          window.webkit={messageHandlers:{hgPreferredIP:{postMessage:body=>{
            nativeCalls.push(body);
            if(body.action==='test'){fixtureRunning=true;return new Promise(r=>window.finishRun=r);}
            return Promise.resolve({supported:true,mode:'auto',isp:'ct',customIPs:[],selectedIP:'',running:fixtureRunning,completed:1,total:3,
              results:[],message:'等待测速'});
          }}}};
        """)
        self.install()
        self.evaluate("document.querySelector('#hgPrefTest').click();Promise.resolve()")
        self.assertFalse(self.evaluate("document.querySelector('#hgPrefCancel').hidden"))
        self.assertTrue(self.evaluate("document.querySelector('#hgPrefSave').disabled"))
        self.evaluate('new Promise(r=>setTimeout(r,650))')
        self.assertIn('1/3', self.evaluate("document.querySelector('#hgPrefResults').textContent"))
        self.evaluate("document.querySelector('#hgPrefCancel').click();Promise.resolve()")
        self.assertEqual(self.evaluate('nativeCalls.at(-1).action'), 'cancel')
        self.evaluate("finishRun({supported:true,mode:'auto',isp:'ct',customIPs:[],selectedIP:'',results:[],message:'已停止测速'});Promise.resolve()")
        self.assertTrue(self.evaluate("document.querySelector('#hgPrefCancel').hidden"))


if __name__ == '__main__':
    unittest.main()
