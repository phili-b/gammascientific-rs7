# PyInstaller spec: one folder holding two programs, rs7 (console) and rs7-gui (windowed).
# Build with: uv run pyinstaller --noconfirm packaging/rs7.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

here = Path(SPECPATH)
datas, binaries, hiddenimports = collect_all("colour")
excludes = ["matplotlib", "tkinter", "IPython", "pytest"]
icon = str(here / "rs7.ico")


def analysis(script):
    return Analysis(
        [str(here / script)],
        pathex=[str(here.parent / "src")],
        datas=datas,
        binaries=binaries,
        hiddenimports=hiddenimports,
        excludes=excludes,
    )


cli, gui = analysis("rs7_cli.py"), analysis("rs7_gui.py")
MERGE((cli, "rs7", "rs7"), (gui, "rs7-gui", "rs7-gui"))

cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="rs7", console=True, icon=icon)
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="rs7-gui", console=False, icon=icon)
COLLECT(
    cli_exe, cli.binaries, cli.datas,
    gui_exe, gui.binaries, gui.datas,
    name="rs7",
)
