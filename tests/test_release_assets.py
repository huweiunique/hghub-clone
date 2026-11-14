"""验证真实 Nightly 清理脚本：完整上传前不得删除旧包。"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), '未安装 Node，无法执行发布清理脚本')
class NightlyAssetTests(unittest.TestCase):
    def execute(self, assets, files=None):
        workflow = (ROOT / '.github/workflows/_build.yml').read_text(encoding='utf-8')
        block = workflow.split('      - name: Nightly 仅保留本次安装包\n', 1)[1]
        script = block.split('          script: |\n', 1)[1].split('\n  # ', 1)[0]
        script = '\n'.join(line[12:] for line in script.splitlines() if line.strip())
        payload = {'script': script, 'assets': assets,
                   'files': files or {'HGhub-current.apk': 10, 'HGhub-current.ipa': 20}}
        harness = r"""
          let input='';process.stdin.on('data',c=>input+=c);process.stdin.on('end',async()=>{
            const p=JSON.parse(input),deleted=[],tags=[];
            const fs={readdirSync:()=>Object.keys(p.files),statSync:name=>({size:p.files[require('path').basename(name)]})};
            const client={paginate:async()=>p.assets,rest:{repos:{listReleaseAssets:()=>{},
              deleteReleaseAsset:async args=>deleted.push(args.asset_id)},git:{updateRef:async args=>tags.push(args)}}};
            let error=null;
            try { await new (Object.getPrototypeOf(async function(){}).constructor)(
              'require','process','github','context','core',p.script)(
              name=>name==='fs'?fs:require(name),{env:{RELEASE_ID:'123'}},client,
              {repo:{owner:'fixture',repo:'fixture'},sha:'current-sha'},{info:()=>{}});
            } catch(e) {error=e.message;}
            console.log(JSON.stringify({deleted,error,tags}));
          });
        """
        result = subprocess.run(['node', '-e', harness], input=json.dumps(payload),
                                text=True, capture_output=True, encoding='utf-8', timeout=10, check=True)
        return json.loads(result.stdout)

    def assets(self):
        return [dict(id=1, name='HGhub-current.apk', size=10, state='uploaded'),
                dict(id=2, name='HGhub-current.ipa', size=20, state='uploaded'),
                dict(id=3, name='HGhub-old.apk', size=9, state='uploaded'),
                dict(id=4, name='old-source.zip', size=30, state='uploaded')]

    def test_success_preserves_current_pair_and_removes_old_files(self):
        result = self.execute(self.assets())
        self.assertEqual(result['deleted'], [3, 4])
        self.assertIsNone(result['error'])
        self.assertEqual(result['tags'], [dict(owner='fixture', repo='fixture', ref='tags/nightly', sha='current-sha', force=False)])

    def test_missing_or_incomplete_upload_cannot_delete_previous_release(self):
        for kind in ['missing', 'size', 'state']:
            with self.subTest(kind=kind):
                assets = self.assets()
                if kind == 'missing':
                    assets.pop(1)
                elif kind == 'size':
                    assets[1]['size'] = 1
                else:
                    assets[1]['state'] = 'starter'
                result = self.execute(assets)
                self.assertEqual(result['deleted'], [])
                self.assertEqual(result['tags'], [])
                self.assertTrue(result['error'])

    def test_local_missing_package_cannot_delete_previous_release(self):
        result = self.execute(self.assets(), {'HGhub-current.apk': 10})
        self.assertEqual(result['deleted'], [])
        self.assertTrue(result['error'])
