"""
RETICLE — 统一路径配置
======================

所有脚本从这里取路径，不再各自硬编码绝对路径（之前老脚本写死的
/Users/shenghangao/Desktop/RETICLE/... 在目录改名成 RETICLE_my 后就失效了）。

路径全部相对于本文件定位，所以整个项目目录可以随意移动/改名。
"""

from pathlib import Path

PROJECT_ROOT   = Path(__file__).resolve().parent.parent

RAW_DATA       = PROJECT_ROOT / "raw_data"
PROCESSED_DATA = PROJECT_ROOT / "processed_data"

DB             = PROCESSED_DATA / "reticle_master.db"

RAW_BIOGRID    = RAW_DATA / "BIOGRID"
PROC_BIOGRID   = PROCESSED_DATA / "BIOGRID"

# BioGRID 每个物种的 screen 元数据 JSON
BIOGRID_METADATA = {
    "Homo sapiens": RAW_BIOGRID / "metadata" / "screen_metadata_homo_sapiens.json",
    "Mus musculus": RAW_BIOGRID / "metadata" / "screen_metadata_musculus.json",
}
