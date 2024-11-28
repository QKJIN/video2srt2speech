from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
from pathlib import Path
import math

from modules import (
    config, 
    websocket, 
    subtitles, 
    audio, 
    speech, 
    translation, 
    video,
    utils
)
from modules.config import DIRS, UPLOAD_DIR, SUBTITLE_DIR

# 创建必要的目录
for dir_path in DIRS:
    dir_path.mkdir(exist_ok=True)

app = FastAPI()

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/subtitled", StaticFiles(directory="subtitled_videos"), name="subtitled")
app.mount("/merged", StaticFiles(directory="merged"), name="merged")
app.mount("/audio", StaticFiles(directory="audio"), name="audio")

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/video/{file_id}")
async def serve_video(file_id: str):
    file_path = UPLOAD_DIR / file_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"inline; filename={file_id}"
        }
    )

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_id = await utils.save_upload_file(file)
        return {"file_id": file_id}
    except Exception as e:
        raise HTTPException(500, f"上传失败: {str(e)}")

@app.websocket("/ws/{file_id}")
async def websocket_endpoint(websocket: WebSocket, file_id: str):
    await websocket.handle_websocket(websocket, file_id)

@app.post("/extract-audio/{file_id}")
async def extract_audio_endpoint(file_id: str):
    return await audio.extract_audio(file_id)

@app.post("/generate-subtitles/{file_id}")
async def generate_subtitles_endpoint(file_id: str, language: str = "zh-CN"):
    try:
        # 获取音频文件路径
        audio_file_id = Path(file_id).stem + '.mp3'
        audio_path = config.AUDIO_DIR / audio_file_id
        
        if not audio_path.exists():
            raise HTTPException(404, "音频文件未找到，请先提取音频")

        # 获取视频时长
        video_path = UPLOAD_DIR / file_id
        video_duration = video.get_video_duration(video_path)

        # 分段处理音频
        segment_duration = 300  # 5分钟一段
        total_segments = math.ceil(video_duration / segment_duration)
        
        all_subtitles = []
        for i in range(total_segments):
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, video_duration)
            
            # 创建临时音频段
            segment_path = config.TEMP_DIR / f"{audio_file_id}_segment_{i}.wav"
            
            # 提取音频段
            await audio.extract_audio_segment(audio_path, segment_path, start_time, end_time)
            
            # 识别语音
            segment_results = await speech.recognize_speech(file_id, segment_path, language)
            all_subtitles.extend(segment_results)
            
            # 清理临时文件
            segment_path.unlink(missing_ok=True)

        # 按开始时间排序
        all_subtitles.sort(key=lambda x: x["start"])

        # 保存字幕文件
        file_id_without_ext = Path(file_id).stem
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        with open(subtitle_path, "w", encoding="utf-8") as f:
            json.dump(all_subtitles, f, ensure_ascii=False, indent=2)
        
        return all_subtitles

    except Exception as e:
        raise HTTPException(500, f"生成字幕失败: {str(e)}")

@app.post("/translate-subtitles/{file_id}")
async def translate_subtitles_endpoint(
    file_id: str, 
    source_language: str, 
    target_language: str
):
    return await translation.translate_subtitles(file_id, source_language, target_language)

@app.get("/available-voices/{language}")
async def get_available_voices(language: str):
    try:
        return {
            "voices": config.SUPPORTED_VOICES.get(language, []),
            "language": language,
            "total": len(config.SUPPORTED_VOICES.get(language, []))
        }
    except Exception as e:
        raise HTTPException(500, f"获取语音列表失败: {str(e)}")

@app.post("/generate-speech/{file_id}/{subtitle_index}")
async def generate_speech_endpoint(
    file_id: str, 
    subtitle_index: int, 
    text: str, 
    voice_name: str = "zh-CN-XiaoxiaoNeural"
):
    return await speech.generate_speech(file_id, subtitle_index, text, voice_name)

@app.post("/merge-audio/{file_id}")
async def merge_audio_endpoint(file_id: str, target_language: str):
    return await audio.merge_audio(file_id, target_language)

@app.post("/burn-subtitles/{file_id}")
async def burn_subtitles_endpoint(
    file_id: str, 
    language: str, 
    style: dict = Body(...)
):
    return await video.burn_subtitles(file_id, language, style)

@app.put("/update-subtitles/{file_id}")
async def update_subtitles_endpoint(file_id: str, data: dict):
    return await subtitles.update_subtitle(file_id, data)

@app.post("/update-subtitle")
async def update_single_subtitle(request: Request):
    data = await request.json()
    return await subtitles.update_subtitle(
        data.get("file_id"), 
        data.get("index"), 
        data.get("text")
    )
