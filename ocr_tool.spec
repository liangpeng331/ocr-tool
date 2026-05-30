# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS .app 打包"""
import os
from PyInstaller.utils.hooks import collect_submodules

# 收集 rapidocr 全部子模块（用 importlib.import_module 动态加载）
rapidocr_hiddenimports = []
try:
    rapidocr_hiddenimports = collect_submodules('rapidocr_onnxruntime')
except Exception:
    # 降级：手动列出
    rapidocr_hiddenimports = [
        'rapidocr_onnxruntime',
        'rapidocr_onnxruntime.rapid_ocr_api',
        'rapidocr_onnxruntime.utils',
        'rapidocr_onnxruntime.ch_ppocr_v3_det',
        'rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect',
        'rapidocr_onnxruntime.ch_ppocr_v3_det.utils',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec.utils',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls.text_cls',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls.utils',
    ]
rapidocr_datas = []
try:
    import rapidocr_onnxruntime
    pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
    for root, _, files in os.walk(pkg_dir):
        for f in files:
            if f.endswith(('.onnx', '.yaml', '.yml', '.txt')):
                src = os.path.join(root, f)
                dst = os.path.relpath(os.path.dirname(src), os.path.dirname(pkg_dir))
                rapidocr_datas.append((src, dst))
except ImportError:
    pass

a = Analysis(
    ['ocr_tool.py'],
    pathex=[],
    binaries=[],
    datas=[
        *rapidocr_datas,
        # 图标文件（可选，嵌入 .app 后可在关于窗口中显示）
        ('icon.icns', '.'),
    ],
    hiddenimports=[
        # PyObjC 模块（部分为动态导入）
        'AppKit',
        'AppKit._AppKit',
        'Foundation',
        'Foundation._Foundation',
        'Quartz',
        'Quartz._Quartz',
        'Vision',
        'Vision._Vision',
        'objc',
        'objc._objc',
        # PIL 插件
        'PIL._imaging',
        # onnxruntime 后端
        'onnxruntime',
        'onnxruntime.capi',
        # rapidocr 动态子模块（importlib.import_module）
        *rapidocr_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不用的 GUI 框架
        'tkinter', 'tcl', 'tk',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'wx',
        # 不用的科学计算
        'scipy', 'pandas', 'matplotlib',
        # 不用的网络/开发
        'IPython', 'jupyter', 'notebook',
        'pytest', 'unittest',
        # 不用的其他模块
        'sqlite3', 'sqlalchemy',
        'curses',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OCR Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,         # UPX 压缩减小体积
    console=False,    # --windowed，不显示终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OCR Tool',
)

app = BUNDLE(
    coll,
    name='OCR Tool.app',
    icon='icon.icns',
    bundle_identifier='com.ocr-tool.screenshot',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'LSUIElement': False,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHumanReadableCopyright': 'Open source OCR screenshot tool',
        'CFBundleDocumentTypes': [],
    },
)
