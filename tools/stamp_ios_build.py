"""为构建后的 iOS Bundle 写入可读构建标识，保留系统数字版本。"""
import argparse
from datetime import datetime
from pathlib import Path
import plistlib
import re


def stamp(app_path, channel, suffix):
    info_path = Path(app_path) / 'Info.plist'
    with info_path.open('rb') as source:
        info = plistlib.load(source)
    version = info['CFBundleShortVersionString']
    if channel == 'nightly':
        match = re.fullmatch(r'-nightly-(\d{8})-([0-9a-f]{7,40})', suffix)
        if not match:
            raise ValueError('Nightly 缺少有效日期及提交号，拒绝生成不可辨认的安装包')
        date = datetime.strptime(match[1], '%Y%m%d')
        commit = match[2][:7]
        label = f'N{date:%y%m%d}-{commit}'
        info.update(HGBuildDate=date.strftime('%Y-%m-%d'), HGBuildCommit=commit)
    elif channel == 'stable':
        if suffix:
            raise ValueError('正式版不应携带 Nightly 后缀')
        label = ''
        info.pop('HGBuildDate', None)
        info.pop('HGBuildCommit', None)
    else:
        raise ValueError('未知构建通道')
    display = f'{version}-{label}' if label else version
    info.update(HGBuildChannel=channel, HGBuildLabel=label,
                HGVersionDescription=display, CFBundleGetInfoString=display)
    # xcodebuild 的 Info.plist 通常是二进制；继续用二进制写回，签名在后续步骤执行。
    with info_path.open('wb') as destination:
        plistlib.dump(info, destination, fmt=plistlib.FMT_BINARY)
    return display


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app_path')
    parser.add_argument('--channel', choices=['nightly', 'stable'], default='stable')
    parser.add_argument('--artifact-suffix', default='')
    args = parser.parse_args()
    print('[ios] 版本标识：' + stamp(args.app_path, args.channel, args.artifact_suffix))


if __name__ == '__main__':
    main()
