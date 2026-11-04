# GUI and engine are separate executables. The GUI never imports device workflows.
from pathlib import Path
root = Path(SPECPATH).resolve().parent
a = Analysis([str(root/'__main__.py')], pathex=[str(root.parent)],
             binaries=[], datas=[(str(root/'resources'),'customer_desktop/resources')], hiddenimports=['tzdata'],
             excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtPdf',
                       'PySide6.QtQml','PySide6.QtQuick','tkinter','matplotlib','numpy'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='TikTokKorean',console=False,
          debug=False,strip=False,upx=False)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='TikTokKorean')
