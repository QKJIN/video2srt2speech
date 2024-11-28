import whisper
import torch
from pathlib import Path
from tqdm import tqdm
import requests
from .config import WHISPER_MODEL_SIZE, WHISPER_MODEL_PATH, MODELS_DIR

def download_model():
    """下载 Whisper 模型"""
    if WHISPER_MODEL_PATH.exists():
        return
    
    MODELS_DIR.mkdir(exist_ok=True)
    
    # Whisper 模型下载 URL
    url = f"https://openaipublic.azureedge.net/main/whisper/{WHISPER_MODEL_SIZE}.pt"
    
    # 下载模型
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    
    with open(WHISPER_MODEL_PATH, 'wb') as f, tqdm(
        desc=f"下载 Whisper {WHISPER_MODEL_SIZE} 模型",
        total=total_size,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
    ) as pbar:
        for data in response.iter_content(chunk_size=1024):
            size = f.write(data)
            pbar.update(size)

def load_model():
    """加载 Whisper 模型"""
    if not WHISPER_MODEL_PATH.exists():
        download_model()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return whisper.load_model(WHISPER_MODEL_PATH, device=device)

async def transcribe_audio(audio_path: Path, language: str = "zh"):
    """使用 Whisper 模型转录音频"""
    model = load_model()
    
    # 转录音频
    result = model.transcribe(
        str(audio_path),
        language=language,
        task="transcribe",
        verbose=True
    )
    
    # 转换为标准格式
    subtitles = []
    for segment in result["segments"]:
        subtitle = {
            "start": segment["start"],
            "duration": segment["end"] - segment["start"],
            "text": segment["text"].strip()
        }
        subtitles.append(subtitle)
    
    return subtitles 