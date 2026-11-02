# PyInstaller spec for the Wiret graph editor. Build with:  python build.py
# (or directly: python -m PyInstaller wiret.spec --noconfirm --clean)
import sys

block_cipher = None

a = Analysis(
    ["wiret_editor.py"],
    pathex=["."],
    datas=[
        ("lessons/*.wiret", "lessons"),        # read-only originals; students edit copies
        ("wiret/std/*.wiret", "wiret/std"),    # std.flow macros, loaded by the registry
    ],
    hiddenimports=[],
    excludes=["pytest", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Wiret",
    console=False,            # no terminal window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="Wiret", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Wiret.app",
        bundle_identifier="org.wiret.editor",
        info_plist={"NSHighResolutionCapable": True,
                    "CFBundleDocumentTypes": [{"CFBundleTypeName": "Wiret source",
                                               "CFBundleTypeExtensions": ["wiret"],
                                               "CFBundleTypeRole": "Editor"}]},
    )
