import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = '森投屏接收端'
PKG_EXE = 'SenAICastReceiver.exe'
MSIX_DIR = os.path.join(HERE, 'msix')
ASSETS = os.path.join(MSIX_DIR, 'Assets')
DIST = os.path.join(HERE, 'dist')
LAYOUT = os.path.join(HERE, 'msix_layout')
IDENTITY_FILE = os.path.join(MSIX_DIR, 'identity.json')


def load_identity():
    ident = {
        'name': os.environ.get('MSSTORE_PACKAGE_IDENTITY_NAME', ''),
        'publisher': os.environ.get('MSSTORE_PUBLISHER', ''),
        'display': os.environ.get('MSSTORE_PUBLISHER_DISPLAY_NAME', ''),
        'display_name': os.environ.get('MSSTORE_DISPLAY_NAME', ''),
        'version': os.environ.get('MSSTORE_VERSION', ''),
    }
    if not (ident['name'] and ident['publisher']):
        try:
            with open(IDENTITY_FILE, encoding='utf-8') as f:
                data = json.load(f)
            ident['name'] = ident['name'] or data.get('name', '')
            ident['publisher'] = ident['publisher'] or data.get('publisher', '')
            ident['display'] = ident['display'] or data.get('display', '')
            ident['display_name'] = ident['display_name'] or data.get('display_name', '')
            ident['version'] = ident.get('version') or data.get('version', '1.2.0.0')
        except Exception:
            pass
    return ident


def render_manifest(dest):
    ident = load_identity()
    src = os.path.join(MSIX_DIR, 'AppxManifest.xml')
    with open(src, encoding='utf-8') as f:
        xml = f.read()
    xml = xml.replace('{{PACKAGE_IDENTITY_NAME}}', ident['name'] or 'SenAICastReceiver')
    xml = xml.replace('{{PUBLISHER}}', ident['publisher'] or 'CN=sunzhiya')
    xml = xml.replace('{{PUBLISHER_DISPLAY_NAME}}', ident['display'] or '森宇基')
    xml = xml.replace('{{DISPLAY_NAME}}', ident['display_name'] or '森投屏接收端')
    xml = xml.replace('{{VERSION}}', ident['version'] or '1.2.0.0')
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(xml)
    return ident


def find_tool(name):
    roots = [
        r'C:\Program Files (x86)\Windows Kits\10\bin',
        r'C:\Program Files\Windows Kits\10\bin',
    ]
    best = None
    for root in roots:
        if not os.path.isdir(root):
            continue
        for ver in sorted(os.listdir(root), reverse=True):
            p = os.path.join(root, ver, 'x64', name)
            if os.path.exists(p):
                if best is None:
                    best = p
    return best


def qt_plugin_dir():
    import PyQt6
    return os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'plugins')


SPEC_TEMPLATE = '''# -*- coding: utf-8 -*-
import os

a = Analysis(
    [%(main)r],
    pathex=[%(here)r],
    binaries=%(binaries)r,
    datas=[(%(assets)r, %(assets_dst)r)],
    hiddenimports=['PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'numpy',
                   'receiver.killswitch', 'receiver.single'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
              'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtSql', 'PyQt6.QtTest',
              'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtDBus'],
    noarchive=False,
)


def _drop_binary(path):
    n = os.path.basename(path).lower()
    return (n == 'opengl32sw.dll' or 'qt6pdf' in n
            or n.startswith('_avif') or n.startswith('_webp'))


a.binaries = [b for b in a.binaries if not _drop_binary(b[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name=%(name)r,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=[%(icon)r],
)
'''


def build_exe():
    plug = qt_plugin_dir()
    mm = os.path.join(plug, 'multimedia')
    bins = []
    for dll in ('ffmpegmediaplugin.dll', 'windowsmediaplugin.dll'):
        p = os.path.join(mm, dll)
        if os.path.exists(p):
            bins.append((p, os.path.join('PyQt6', 'Qt6', 'plugins', 'multimedia')))
    spec = SPEC_TEMPLATE % {
        'main': os.path.join(HERE, 'main.py'),
        'here': HERE,
        'binaries': bins,
        'assets': os.path.join(HERE, 'receiver', 'assets'),
        'assets_dst': os.path.join('receiver', 'assets'),
        'name': NAME,
        'icon': os.path.join(HERE, 'receiver', 'assets', 'icon.ico'),
    }
    spec_path = os.path.join(HERE, '_build.spec')
    with open(spec_path, 'w', encoding='utf-8') as f:
        f.write(spec)
    print('[1/4] PyInstaller 打包 exe ...')
    r = subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--clean', spec_path], cwd=HERE)
    if r.returncode != 0:
        print('!! PyInstaller 失败')
        return None
    exe = os.path.join(DIST, NAME + '.exe')
    if not os.path.exists(exe):
        print('!! 没找到 exe: %s' % exe)
        return None
    print('    -> %s (%.1f MB)' % (exe, os.path.getsize(exe) / 1024 / 1024))
    return exe


def prepare_layout(exe):
    print('[2/4] 组装 layout ...')
    if os.path.isdir(LAYOUT):
        shutil.rmtree(LAYOUT)
    os.makedirs(LAYOUT)
    shutil.copy2(exe, os.path.join(LAYOUT, PKG_EXE))
    ident = render_manifest(os.path.join(LAYOUT, 'AppxManifest.xml'))
    if os.path.isdir(ASSETS):
        shutil.copytree(ASSETS, os.path.join(LAYOUT, 'Assets'))
    print('    Identity Name   = %s' % (ident['name'] or '(未设置，用占位值——上传会被打回)'))
    print('    Publisher       = %s' % (ident['publisher'] or '(未设置，用占位值——上传会被打回)'))
    print('    DisplayName     = %s' % (ident['display'] or '(未设置)'))
    print('    Version         = %s' % (ident['version'] or '1.2.0.0'))
    if not (ident['name'] and ident['publisher']):
        print('    !! 提示：还没填真实商店身份。')
        print('       打包后在 Partner Center 上传会被打回：')
        print('         无效的软件包标识名称 / 无效的软件包发布者名称')
        print('       填法：把 Partner Center 产品标识页的三个值写进')
        print('         %s' % IDENTITY_FILE)
        print('       或设环境变量 MSSTORE_PACKAGE_IDENTITY_NAME / MSSTORE_PUBLISHER /')
        print('                  MSSTORE_PUBLISHER_DISPLAY_NAME')
    for f in os.listdir(LAYOUT):
        print('    %s' % f)
    return LAYOUT


def pack_msix():
    makeappx = find_tool('makeappx.exe')
    if not makeappx:
        print('!! 找不到 makeappx.exe')
        print('   装 Visual Studio 的「应用开发工作负载」，或单独装 Windows SDK')
        return None
    print('[3/4] makeappx pack ...')
    out = os.path.join(DIST, NAME + '.msix')
    if os.path.exists(out):
        os.remove(out)
    cmd = [makeappx, 'pack', '/d', LAYOUT, '/p', out, '/o']
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='ignore')
    if r.returncode != 0:
        print('!! makeappx 失败:')
        print((r.stdout or '') + (r.stderr or ''))
        return None
    size = os.path.getsize(out) / 1024 / 1024
    print('    -> %s (%.1f MB)' % (out, size))
    return out


def _make_self_signed(cert_dir):
    pfx = os.path.join(cert_dir, 'senai.pfx')
    cer = os.path.join(cert_dir, 'senai.cer')
    if os.path.exists(pfx):
        return pfx, cer
    os.makedirs(cert_dir, exist_ok=True)
    ps = (
        "$ErrorActionPreference='Stop';"
        "$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=sunzhiya' "
        "-CertStoreLocation Cert:\\CurrentUser\\My "
        "-NotAfter (Get-Date).AddYears(5);"
        "Export-PfxCertificate -Cert $c -FilePath '%s' -Password (ConvertTo-SecureString "
        "'senai' -AsPlainText -Force) | Out-Null;"
        "Export-Certificate -Cert $c -FilePath '%s' | Out-Null;"
        "Write-Output 'OK'"
    ) % (pfx, cer)
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                       capture_output=True, text=True,
                       encoding='utf-8', errors='ignore')
    if not os.path.exists(pfx):
        print('!! 自签证书生成失败: %s' % ((r.stdout or '') + (r.stderr or ''))[:300])
        return None, None
    return pfx, cer


def sign_local(msix):
    signtool = find_tool('signtool.exe')
    if not signtool:
        print('[4/4] 跳过本地签名（缺 signtool.exe）')
        return None
    cert_dir = os.path.join(HERE, 'msix_cert')
    pfx, _cer = _make_self_signed(cert_dir)
    if not pfx:
        return None
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix='msixsign_')
    tmp_in = os.path.join(tmpdir, 'app.msix')
    tmp_out = os.path.join(tmpdir, 'app-signed.msix')
    shutil.copy2(msix, tmp_in)
    shutil.copy2(tmp_in, tmp_out)
    env = dict(os.environ)
    env['MSYS2_ARG_CONV_EXCL'] = '*'
    r = subprocess.run([signtool, 'sign', '/fd', 'SHA256', '/f', pfx,
                        '/p', 'senai', tmp_out],
                       capture_output=True, text=True, env=env,
                       encoding='utf-8', errors='ignore')
    if r.returncode != 0 or not os.path.exists(tmp_out):
        print('!! 签名失败（不影响上传商店）:')
        print((r.stdout or '') + (r.stderr or ''))
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    signed = msix.replace('.msix', '-signed.msix')
    shutil.move(tmp_out, signed)
    shutil.rmtree(tmpdir, ignore_errors=True)
    print('    -> %s' % signed)
    return signed


def main():
    exe = build_exe()
    if not exe:
        return 1
    prepare_layout(exe)
    msix = pack_msix()
    if not msix:
        return 1
    signed = sign_local(msix)
    print('')
    print('=' * 60)
    print('MSIX 打包完成')
    print('  上传商店用: %s' % msix)
    if signed:
        print('  本机试装用: %s' % signed)
        print('  （双击安装会提示未知发布者，选「安装」即可）')
    print('')
    print('下一步：')
    print('  1. 注册 Partner Center 账号（2026 年起个人账号免费）')
    print('     https://partner.microsoft.com/dashboard')
    print('  2. 预留应用名「森投屏接收端」')
    print('  3. 新建 MSIX 应用 → 上传上面的 .msix')
    print('  4. 填商店页（截图/描述/隐私政策）→ 提交认证')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
