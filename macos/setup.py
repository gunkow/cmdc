import sysconfig
import tomllib
from pathlib import Path

import charset_normalizer
from setuptools import setup


PROJECT_ROOT = Path(__file__).parents[1]
PROJECT = tomllib.loads(
    (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
)["project"]

EXTENSION_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
CHARSET_SITE_PACKAGES = Path(charset_normalizer.__file__).parent.parent
CHARSET_EXTENSIONS = sorted(
    Path(charset_normalizer.__file__).parent.glob(f"*{EXTENSION_SUFFIX}")
)
MYPYC_SUPPORT_EXTENSIONS = sorted(
    CHARSET_SITE_PACKAGES.glob(f"*__mypyc*{EXTENSION_SUFFIX}")
)
MYPYC_SUPPORT_MODULES = [
    extension.name.removesuffix(EXTENSION_SUFFIX)
    for extension in MYPYC_SUPPORT_EXTENSIONS
]
if CHARSET_EXTENSIONS and not MYPYC_SUPPORT_MODULES:
    raise RuntimeError(
        "charset_normalizer has compiled extensions, but its mypyc support "
        "module could not be found"
    )

APP = [{"script": "launcher.py", "dest_base": "cmdc"}]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["cmdc", "pynput", "charset_normalizer"],
    "includes": MYPYC_SUPPORT_MODULES,
    "plist": {
        "CFBundleDisplayName": "cmdc",
        "CFBundleName": "cmdc",
        "CFBundleIdentifier": "com.gunkow.cmdc",
        "CFBundleShortVersionString": PROJECT["version"],
        "CFBundleVersion": PROJECT["version"],
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
}


setup(app=APP, options={"py2app": OPTIONS}, setup_requires=["py2app"])
