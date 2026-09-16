# scripts/build_index.py
"""
id_order 是行号反查的唯一依据 —— faiss 只告诉你"第 7 行最像"，你要靠 id_order[7] 才知道是哪个样本。漏了它，检索结果就是一堆无意义的数字（指南坑表第 2 条）。
IndexFlatIP 而不是 IndexFlatL2 —— 向量已归一化，内积才等于余弦相似度。用 L2 会得到一套错误的排序，而且不报错。
自动备份 —— 这个脚本会改写 samples.json。有备份，中途崩了能还原
"""


"""离线建向量索引：samples.json → clip_vectors.npz + faiss.index，并回填 clip_vec_index。

⚠️ 这个脚本会**改写** data/samples.json（回填 clip_vec_index）。
   所以它跑之前会先自动备份到 data/samples.json.bak —— 中途失败能还原。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/build_index.py
"""
import json
import shutil
import sys
import time
from pathlib import Path

import faiss
import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clip_model import encode_images          # 单例加载，不要在这里调 load_from_name
from src.utils import CFG, resolve_path

SAMPLES = ROOT / "data" / "samples.json"
BACKUP = ROOT / "data" / "samples.json.bak"
INDEX_DIR = Path(CFG["paths"]["index"])           # utils.py 已锚成绝对路径
NPZ = INDEX_DIR / "clip_vectors.npz"
FAISS = INDEX_DIR / "faiss.index"


def main() -> int:
    if not SAMPLES.exists():
        sys.exit(f"[FAIL] 找不到 {SAMPLES}")

    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    if not samples:
        sys.exit("[FAIL] 样本库是空的")

    # ---- 备份（下面要回填字段，出问题能还原）----
    shutil.copy2(SAMPLES, BACKUP)
    print(f"[OK] 已备份 → {BACKUP.relative_to(ROOT)}")

    paths = [resolve_path(s["image_path"]) for s in samples]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"[警告] {len(missing)} 张图片不存在，会被跳过：")
        for m in missing[:5]:
            print(f"        {m}")

    # ---- 批量编码 ----
    print(f"[..] 开始编码 {len(paths)} 张图（CPU 上要几分钟，别以为卡死）")
    t0 = time.time()
    mat, ok_paths, bad = encode_images([str(p) for p in paths])
    print(f"[OK] 编码完成，耗时 {time.time() - t0:.1f}s；成功 {len(ok_paths)} 张，坏图 {len(bad)} 张")
    for p, why in bad[:5]:
        print(f"        坏图 {p}：{why}")

    if not len(ok_paths):
        sys.exit("[FAIL] 一张图都没编码成功，检查 data/images/")

    # ---- 行号映射：faiss 只返回行号，必须能反查回 sample_id ----
    ok_set = {str(Path(p).resolve()) for p in ok_paths}
    id_order = [s["id"] for s, p in zip(samples, paths) if str(p.resolve()) in ok_set]
    assert len(id_order) == mat.shape[0], f"行号映射对不上：{len(id_order)} vs {mat.shape[0]}"

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(NPZ, vectors=mat, id_order=np.array(id_order))
    print(f"[OK] 向量已保存 → {NPZ.relative_to(ROOT)}  ({mat.shape[0]} × {mat.shape[1]})")

    # ---- faiss：向量已 L2 归一化，所以内积 = 余弦，用 IndexFlatIP ----
    index = faiss.IndexFlatIP(mat.shape[1])
    index.add(mat.astype("float32"))
    faiss.write_index(index, str(FAISS))
    print(f"[OK] faiss 索引已保存 → {FAISS.relative_to(ROOT)}（IndexFlatIP，{index.ntotal} 条）")

    # ---- 回填 clip_vec_index ----
    pos = {sid: i for i, sid in enumerate(id_order)}
    for s in samples:
        s["clip_vec_index"] = pos.get(s["id"])       # 图片缺失的条目明确置 None，别留旧值
    SAMPLES.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 已回填 clip_vec_index：{len(pos)} / {len(samples)} 条")

    print("\n[PASS] 索引建成。下一步跑 scripts/smoke_retrieve.py 验证检索效果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
