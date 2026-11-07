"""学科包能力探测:只报告已安装的包,不自动安装、不导入重依赖。"""
from __future__ import annotations

import importlib.util

PACKAGES = {
    "rdkit": "rdkit",
    "biopython": "Bio",
    "astropy": "astropy",
    "networkx": "networkx",
}


def available_packs() -> dict[str, bool]:
    return {
        name: importlib.util.find_spec(module) is not None
        for name, module in PACKAGES.items()
    }
