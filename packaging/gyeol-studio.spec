# PyInstaller spec: one folder with the launcher (Windows: gyeol-studio.exe; macOS: 결 스튜디오.app).
#   pyinstaller packaging/gyeol-studio.spec --noconfirm
# Model weights are not bundled: the app downloads them on first run (gyeol fetch).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON_DIR = ROOT / "packaging" / "icons"
NAME = "gyeol-studio"

hidden = (
    collect_submodules("gyeol")  # analysis modules are imported lazily by name
    + collect_submodules("gyeol_studio")
    + collect_submodules("uvicorn")
    + ["multipart", "python_multipart", "qrcode.image.svg", "yaml", "scipy.signal", "soundfile"]
)
datas = collect_data_files("gyeol") + collect_data_files("gyeol_studio") + collect_data_files("soundfile")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "IPython", "notebook", "pytest", "torchvision", "torchaudio.prototype"],
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = str(ICON_DIR / ("icon.ico" if sys.platform == "win32" else "icon.icns"))
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,  # a small window (Tk) shows the app's state; closing it quits the app
    icon=icon if Path(icon).exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="결 스튜디오.app",
        icon=icon if Path(icon).exists() else None,
        bundle_identifier="dev.iruki.gyeol-studio",
        info_plist={
            "CFBundleDisplayName": "결 스튜디오",
            "NSMicrophoneUsageDescription": "브라우저에서 노래를 녹음할 때 마이크를 써요.",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
