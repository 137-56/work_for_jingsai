# scripts/smoke_clip.py
"""Step 3 冒烟测试：读一张图 → 输出 512 维向量 → 检查 L2 范数 ≈ 1.0

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/smoke_clip.py "图片路径"
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clip_model import get_clip_model, encode_image, encode_text


def pick_image():
    if len(sys.argv) > 1:                          # 命令行给了路径就用它
        return Path(sys.argv[1])
    img_dir = ROOT / "data" / "images"
    hits = sorted(img_dir.glob("*.png")) + sorted(img_dir.glob("*.jpg"))
    if hits:                                       # 否则用样本库第一张
        return hits[0]
    sys.exit("用法：python scripts/smoke_clip.py <图片路径>")


def main():
    img_path = pick_image()
    if not img_path.exists():
        sys.exit(f"[FAIL] 图片不存在：{img_path}")
    print(f"[1/5] 测试图片：{img_path}")

    t0 = time.time()
    get_clip_model()                               # 首次调用会下载 + 加载权重
    print(f"[2/5] 模型就绪，耗时 {time.time() - t0:.1f}s")

    t1 = time.time()
    vec = encode_image(img_path)
    print(f"[3/5] 图像编码完成，耗时 {time.time() - t1:.2f}s")

    dim = vec.shape[-1]
    norm = float(vec.norm(dim=-1)[0])
    print(f"[4/5] 向量维度 = {dim}（期望 512）")
    print(f"      L2 norm  = {norm:.6f}（期望 ≈ 1.0）")
    print(f"      前 5 个数值：{[round(float(x), 6) for x in vec[0][:5]]}")

    # ---- 第 5 步：图文相似度自检 ----
    positive = "植物花卉纹：缠枝莲纹"                       # 这张图的正样本描述
    cands = [positive, "动物瑞兽纹：龙纹",
             "几何锦纹：回纹", "文字福寿纹：福字纹"]
    sims = (encode_text(cands) @ vec.T).squeeze(-1)     # (4,512)@(512,1) → (4,)
    print("[5/5] 图文相似度自检（Top-1 应该是正样本）")
    for i in sims.argsort(descending=True).tolist():     # 从大到小遍历
        mark = "  ← 命中" if cands[i] == positive else ""
        print(f"      {sims[i]:.4f}  {cands[i]}{mark}")

    top1_ok = cands[int(sims.argmax())] == positive
    ok = (dim == 512) and abs(norm - 1.0) < 1e-3 and top1_ok
    print("\n" + ("[PASS] Step 3 通过" if ok else "[FAIL] 不达标，见上面输出"))
    return 0 if ok else 1

    



if __name__ == "__main__":
    sys.exit(main())
