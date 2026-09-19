# -*- mode: python ; coding: utf-8 -*-
# 浩威刷题 打包配置
# 构建命令: pyinstaller --noconfirm --clean 浩威刷题.spec

ROOT = r'D:\浩威刷题'

a = Analysis(
    ['desktop.py'],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (ROOT + '\\templates', 'templates'),
        (ROOT + '\\static', 'static'),
        (ROOT + '\\icon.ico', '.'),
    ],
    hiddenimports=[
        'init_db',
        'utils.recommendation',
        'utils.word_parser',
        'docx',
        'lxml',
        'webview',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='浩威刷题',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ROOT + '\\icon.ico',
)