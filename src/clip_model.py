# src/clip_model.py
#把模型加载和编码封起来
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from PIL import Image
import cn_clip.clip as clip
from cn_clip.clip import load_from_name

from src.utils import CFG


def get_device():
    return CFG["clip"]["device"]


@lru_cache(maxsize=1)#核心
#load_from_name() 每调用一次就把权重重新读进内存，几秒钟。而检索是"每次查询都要编码文本"的操作——每次都重载，演示时卡成幻灯片。lru_cache 把它缓存成进程内唯一实例，第二次调用直接返回，不再读盘。
def get_clip_model():
    """返回 (model, preprocess)。lru_cache(maxsize=1) 保证整进程只加载一次。
    所以这个函数不能带参数——否则参数一变就绕过缓存。模型名一律从 CFG 读。"""
    cfg = CFG["clip"]
    model, preprocess = load_from_name(
        cfg["model_name"],                   # ViT-B-16
        device=cfg["device"],                # cpu
        download_root=cfg["download_root"],  # utils.py 已锚成绝对路径 work/ckpt
        use_modelscope=True,                 # 从 ModelScope 拉，国内直连
    )
    model.eval()
    return model, preprocess


@torch.no_grad()
def encode_image(image_path):
    """读一张图 → L2 归一化后的图像向量，shape = (1, 512)。"""
    model, preprocess = get_clip_model()
    img = Image.open(image_path).convert("RGB")
    batch = preprocess(img).unsqueeze(0).to(get_device())
    feat = model.encode_image(batch)
    feat = feat / feat.norm(dim=-1, keepdim=True)     # ★ 必须归一化，缺了排序全乱
    return feat.float().cpu()

@torch.no_grad()
def encode_images(image_paths, batch_size=None):
    """批量编码（建索引用）。返回 (mat, ok_paths, bad)：
        mat      —— (N, 512) 的 float32 数组，行序与 ok_paths 一一对应
        ok_paths —— 成功读入的图片路径（顺序与输入一致，坏图被跳过）
        bad      —— 读不进来的坏图 [(路径, 原因)]

    为什么要批量版而不是循环调 encode_image：
        单张调用每次都要过一次 preprocess + 前向。30 张还能忍，300 张就很慢。
        批量把多张堆成一个 tensor 一次前向，CPU 上快好几倍。

    为什么要把坏图收集起来而不是直接抛异常：
        样本图来自公开渠道，难免有损坏或非图片文件。
        一张坏图不该让整批编码中断（指南坑表第 5 条）。
    """
    model, preprocess = get_clip_model()
    bs = batch_size or CFG["clip"]["batch_size"]

    vecs, ok_paths, bad = [], [], []
    for i in range(0, len(image_paths), bs):
        tensors, kept = [], []
        for p in image_paths[i:i + bs]:
            try:
                img = Image.open(p).convert("RGB")
                tensors.append(preprocess(img))
                kept.append(p)
            except Exception as e:                    # 坏图跳过，不拖垮整批
                bad.append((str(p), f"{type(e).__name__}: {e}"))
        if not tensors:
            continue
        batch = torch.stack(tensors).to(get_device())
        feat = model.encode_image(batch)
        feat = feat / feat.norm(dim=-1, keepdim=True)  # ★ 与单图版一致，必须归一化
        vecs.append(feat.float().cpu().numpy())
        ok_paths.extend(kept)

    mat = np.vstack(vecs) if vecs else np.zeros((0, 512), dtype="float32")
    return mat, ok_paths, bad



@torch.no_grad()
def encode_text(texts):
    """一段或多段中文文本 → L2 归一化后的向量，shape = (n, 512)。
    文本侧必须走 clip.tokenize，与图像侧的 preprocess 配对。"""
    model, _ = get_clip_model()
    if isinstance(texts, str):
        texts = [texts]
    tokens = clip.tokenize(texts).to(get_device())
    feat = model.encode_text(tokens)
    feat = feat / feat.norm(dim=-1, keepdim=True)     # ★ 与图像侧保持一致
    return feat.float().cpu()
