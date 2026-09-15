# src/utils.py
#os 用来获取环境变量,文件操作,获取当前工作目录,操作路径
#yaml 读取yaml格式的配置文件
import os, yaml
#Path 用来处理文件路径的工具
from pathlib import Path
#_file_当前python文件的自己路径
#resolve() 得到当前文件的绝对路径
#第一个.parent 当前路径的上一级目录 , 第二个就是再往上一个
ROOT = Path(__file__).resolve().parent.parent
#load_config() 用来加载config的函数
def load_config():
    #打开config.yaml open(文件位置,编码格式)
    #with 可以自动关闭文件 , 不需要close
    #取名为f
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        #yaml文件解析成python数据结构
        return yaml.safe_load(f)

#加载api密钥
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

#CFG整个项目的配置字典
CFG = load_config()

# --- 把配置里的相对路径锚定到项目根目录 ROOT ---
# config.yaml 里的 "data/samples.json" 是相对「当前所在目录」的，
# 换个目录启动就指错了。统一拼上 ROOT，变成绝对路径，从哪启动都对。
def _abs(p):
    # ROOT / p：把 ROOT 和相对路径拼起来
    # .resolve()：转成绝对路径（顺便把 ./ 和 ../ 收敛掉）
    # str()：转回字符串，因为后面代码是拿字符串做拼接的（如 paths.index + "/faiss.index"）
    return str((ROOT / p).resolve())


def resolve_path(p):
    """把工程内的相对路径解析成绝对路径（已经是绝对路径的原样返回）。

    为什么需要它：config.yaml 里的 paths 已经在上面锚定过了，但 data/samples.json
    里的 image_path（如 'data/images/WENYANG-001.jpg'）仍然是相对路径。
    M2/M4/M6 都要读它——统一走这里，别在每个模块里各拼一次 ROOT。"""
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p).resolve()

# 模型权重下载目录：'./ckpt' 这类必须锚定，否则权重会下到乱七八糟的地方
CFG["clip"]["download_root"] = _abs(CFG["clip"]["download_root"])

# 逐个把 paths 下的四条路径都锚定（samples / rules / index / outputs）
for _k, _v in CFG["paths"].items():
    CFG["paths"][_k] = _abs(_v)