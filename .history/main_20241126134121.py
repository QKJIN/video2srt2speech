from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
from pathlib import Path
import math
import asyncio

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
async def websocket_endpoint(ws: WebSocket, file_id: str):
    await websocket.handle_websocket(ws, file_id)

@app.post("/extract-audio/{file_id}")
async def extract_audio_endpoint(file_id: str):
    return await audio.extract_audio(file_id)

@app.post("/generate-subtitles/{file_id}")
async def generate_subtitles_endpoint(file_id: str, language: str = "zh-CN"):
    return await subtitles.generate_subtitles(file_id, language)

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

@app.post("/generate-speech-file/{file_id}")
async def generate_speech_file_endpoint(
    file_id: str,
    target_language: str,
    voice_name: str = "zh-CN-XiaoxiaoNeural"
):
    return await speech.generate_speech_for_file(file_id, target_language, voice_name)

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
