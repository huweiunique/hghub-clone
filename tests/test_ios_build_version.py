"""对真实 plist 写入器验证构建日期、提交和数字版本保留。"""
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from stamp_ios_build import stamp


class IOSBuildVersionTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.test-tmp').mkdir(exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=ROOT / '.test-tmp')
        self.addCleanup(self.work.cleanup)
        self.app = Path(self.work.name) / 'HGhub.app'
        self.app.mkdir()
        self.info = self.app / 'Info.plist'
        self.original = {'CFBundleShortVersionString': '1.2.0.8', 'CFBundleVersion': '1208',
                         'CFBundleIdentifier': 'fixture.hghub'}
        self.info.write_bytes(plistlib.dumps(self.original))

    def test_nightly_is_compact_and_preserves_numeric_versions(self):
        full_sha = '9478076030273c33d3fa194fcb784cc742eea11e'
        result = stamp(self.app, 'nightly', '-nightly-20261113-' + full_sha)
        self.assertEqual(result, '1.2.0.8-N261113-9478076')
        self.assertNotIn(' ', result)
        info = plistlib.loads(self.info.read_bytes())
        for key, value in self.original.items():
            self.assertEqual(info[key], value)
        self.assertEqual(info['HGBuildDate'], '2026-11-13')
        self.assertEqual(info['HGBuildCommit'], '9478076')
        self.assertEqual(info['HGBuildLabel'], 'N261113-9478076')
        self.assertEqual(info['HGVersionDescription'], result)
        self.assertEqual(info['CFBundleGetInfoString'], result)

    def test_invalid_nightly_metadata_does_not_change_bundle(self):
        before = self.info.read_bytes()
        for suffix in ['', '-nightly-20260230-9478076', '-nightly-20261113-bad', '-nightly-20261113-9478076 ']:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                stamp(self.app, 'nightly', suffix)
            self.assertEqual(before, self.info.read_bytes())

    def test_stable_does_not_keep_previous_nightly_metadata(self):
        stamp(self.app, 'nightly', '-nightly-20261113-9478076')
        self.assertEqual(stamp(self.app, 'stable', ''), '1.2.0.8')
        info = plistlib.loads(self.info.read_bytes())
        self.assertEqual(info['HGBuildChannel'], 'stable')
        self.assertNotIn('HGBuildDate', info)
        self.assertNotIn('HGBuildCommit', info)
        self.assertEqual(info['HGBuildLabel'], '')

    def test_stable_rejects_nightly_suffix(self):
        with self.assertRaises(ValueError):
            stamp(self.app, 'stable', '-nightly-20261113-9478076')
