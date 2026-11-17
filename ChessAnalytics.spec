# Build both desktop and console launchers sharing one dependency folder.
from PyInstaller.utils.hooks import collect_data_files

a = Analysis(['cw2.py'], pathex=[], binaries=[],
             datas=collect_data_files('matplotlib'),
             hiddenimports=['matplotlib.backends.backend_tkagg'],
             hookspath=[], hooksconfig={'matplotlib': {'backends': ['TkAgg']}},
             runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='cw2',
          debug=False, strip=False, upx=False, console=True)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ChessAnalytics',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(cli, gui, a.binaries, a.datas, strip=False, upx=False, name='ChessAnalytics')
