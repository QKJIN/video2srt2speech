import whisper
import torch
from pathlib import Path
from tqdm import tqdm
import requests
from .config import WHISPER_MODEL_SIZE, WHISPER_MODEL_PATH, MODELS_DIR

# 添加语言代码映射
LANGUAGE_CODE_MAP = {
    "zh-CN": "zh",
    "zh-TW": "zh",
    "en-US": "en",
    "en": "en",
    "ja-JP": "ja",
    "ja": "ja",
    "ko-KR": "ko",
    "ko": "ko",
    "fr-FR": "fr",
    "fr": "fr",
    "de-DE": "de",
    "de": "de"
}

def download_model():
    """下载 Whisper 模型"""
    if WHISPER_MODEL_PATH.exists():
        return
    
    MODELS_DIR.mkdir(exist_ok=True)
    print(f"开始下载 Whisper {WHISPER_MODEL_SIZE} 模型...")
    
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
    
    print("Whisper 模型下载完成")

def load_model():
    """加载 Whisper 模型"""
    if not WHISPER_MODEL_PATH.exists():
        download_model()
    
    print("正在加载 Whisper 模型...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(WHISPER_MODEL_SIZE, device=device)
    print(f"Whisper 模型加载完成，使用设备: {device}")
    return model

async def transcribe_audio(audio_path: Path, language: str = "zh"):
    """使用 Whisper 模型转录音频"""
    try:
        # 转换语言代码
        whisper_language = LANGUAGE_CODE_MAP.get(language, language)
        print(f"使用 Whisper 转录音频，语言: {whisper_language}")
        
        model = load_model()
        
        # 转录音频
        print(f"开始转录音频文件: {audio_path}")
        result = model.transcribe(
            str(audio_path),
            language=whisper_language,
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
        
        print(f"转录完成，生成了 {len(subtitles)} 条字幕")
        return subtitles
        
    except Exception as e:
        print(f"Whisper 转录失败: {str(e)}")
        raise 