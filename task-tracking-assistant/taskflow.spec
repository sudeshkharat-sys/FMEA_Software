# PyInstaller spec: one self-contained TaskFlow.exe (build with build_exe.bat on Windows).
from PyInstaller.utils.hooks import collect_all

datas = [("static", "static")]
binaries, hiddenimports = [], ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                               "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "multipart"]
for pkg in ["uvicorn", "fastapi", "starlette", "pydantic", "pydantic_core", "httpx", "openpyxl", "truststore", "anyio"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

a = Analysis(["launcher.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "notebook", "IPython"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], name="TaskFlow", console=True, upx=False)
