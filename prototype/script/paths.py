"""
RETICLE — 统一路径配置
======================

所有脚本从这里取路径，不再各自硬编码绝对路径。

两种运行环境，同一份代码：
  * 本地 Mac        —— 不设环境变量，路径相对本项目目录(processed_data/、raw_data/)。
  * Compute2 (RIS)  —— 设 RETICLE_DATA=/storage3/fs1/aorvedahl-RETICLE/Active/data，
                       processed_data / 原始 BioGRID 都指向 RIS 存储。

RIS 上的原始数据布局和本地不同(BIOGRID-ORCS-2.0.18/ 里直接放物种子目录 + 元数据
JSON)，所以下面对原始目录做“探测两种布局”处理。
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# RETICLE_DATA: 集群上指向 RIS 存储的 data 根目录；本地不设则回落到项目内。
_DATA_ENV = os.environ.get("RETICLE_DATA")
DATA_ROOT = Path(_DATA_ENV).resolve() if _DATA_ENV else PROJECT_ROOT

# ---- 输出 / 派生数据 -------------------------------------------------------
PROCESSED_DATA = (DATA_ROOT / "processed_data") if _DATA_ENV else (PROJECT_ROOT / "processed_data")
try:                                    # 只在 data 根已存在时创建 processed_data 子目录
    PROCESSED_DATA.mkdir(exist_ok=True)
except OSError:
    pass                                # data 根不存在(如在别的机器上 import)——不报错
DB = PROCESSED_DATA / "reticle_master.db"


# ---- 原始 BioGRID(两种布局都探测) ----------------------------------------
def _first_existing(cands):
    for c in cands:
        if c.exists():
            return c
    return cands[0]


# 原始屏文件根目录:RIS = .../BIOGRID-ORCS-2.0.18 ; 本地 = raw_data/BIOGRID
RAW_BIOGRID = _first_existing([
    DATA_ROOT / "BIOGRID-ORCS-2.0.18",     # RIS 布局
    DATA_ROOT / "raw_data" / "BIOGRID",    # 若 RETICLE_DATA 指到项目根
    PROJECT_ROOT / "raw_data" / "BIOGRID", # 本地
])
RAW_DATA = RAW_BIOGRID.parent
PROC_BIOGRID = PROCESSED_DATA / "BIOGRID"


def _biogrid_metadata(species_file):
    """元数据 JSON 在 RIS 直接放在 BIOGRID-ORCS-2.0.18/ 下；本地在 metadata/ 子目录。"""
    return _first_existing([
        RAW_BIOGRID / species_file,                 # RIS 布局
        RAW_BIOGRID / "metadata" / species_file,    # 本地布局
    ])


BIOGRID_METADATA = {
    "Homo sapiens": _biogrid_metadata("screen_metadata_homo_sapiens.json"),
    "Mus musculus": _biogrid_metadata("screen_metadata_musculus.json"),
}


def _biogrid_screens(species):
    """Per-species raw screen dir. RIS = BIOGRID-ORCS-2.0.18/<species>/ ;
    local = raw_data/BIOGRID/screenings/<species>/."""
    return _first_existing([
        RAW_BIOGRID / species,                 # RIS layout
        RAW_BIOGRID / "screenings" / species,  # local layout
    ])


BIOGRID_SCREENS = {
    "Homo sapiens": _biogrid_screens("homo_sapiens"),
    "Mus musculus": _biogrid_screens("mus_musculus"),
}
