"""Build script to package Kratos Agent into a standalone Windows executable."""
import sys
import subprocess
import shutil
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
SPEC_FILE = BASE_DIR / "kratos_agent.spec"
ICON_FILE = BASE_DIR / "kratos.ico"
BANNER_FILE = BASE_DIR / "kratos_banner.png"
OPENPETS_PLUGIN_DIR = BASE_DIR / "openpets" / "kratos-companion"

def prepare_icon():
    """Generates kratos.ico from banner image if not present."""
    if not ICON_FILE.exists() and BANNER_FILE.exists():
        print("Creating kratos.ico from kratos_banner.png...")
        try:
            img = Image.open(BANNER_FILE)
            img.resize((256, 256)).save(
                ICON_FILE,
                format="ICO",
                sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
            )
            print("kratos.ico generated successfully.")
        except Exception as e:
            print(f"Warning: Could not create icon: {e}")

def run_build():
    print("=" * 60)
    print("  Building Kratos Agent Standalone Windows Executable (.exe)")
    print("=" * 60)
    
    prepare_icon()

    if not OPENPETS_PLUGIN_DIR.is_dir():
        print(f"[ERROR] OpenPets companion plugin not found: {OPENPETS_PLUGIN_DIR}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_FILE),
    ]

    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(BASE_DIR))

    if result.returncode != 0:
        print(f"\n[ERROR] PyInstaller build failed with return code {result.returncode}")
        sys.exit(result.returncode)

    exe_path = DIST_DIR / "kratos-agent.exe"
    if exe_path.exists():
        companion_path = DIST_DIR / "openpets" / "kratos-companion"
        if companion_path.exists():
            shutil.rmtree(companion_path)
        shutil.copytree(OPENPETS_PLUGIN_DIR, companion_path, dirs_exist_ok=True)
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print(f"  Executable: {exe_path}")
        print(f"  OpenPets:   {companion_path}")
        print(f"  Size:       {size_mb:.2f} MB")
        print("=" * 60)
    else:
        print(f"\n[ERROR] Expected executable not found at {exe_path}")
        sys.exit(1)

if __name__ == "__main__":
    run_build()
