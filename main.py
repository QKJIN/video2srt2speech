from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, Body, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
from pathlib import Path
import math
import asyncio
import zipfile
import os

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
from modules.config import DIRS, UPLOAD_DIR, SUBTITLE_DIR, TEMP_DIR, AUDIO_DIR
from pydantic import BaseModel
from typing import Optional

# 定义请求模型
class SingleTranslationRequest(BaseModel):
    index: int
    text: str
    source_language: str
    target_language: str

class SingleSpeechRequest(BaseModel):
    index: int
    target_language: str
    use_local_tts: bool = False
    voice_name: Optional[str] = None
    speed: float = 1.0  # 添加语速参数，默认值为1.0

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
async def upload_file(
    file: UploadFile = File(...),
    file_id: str = Form(None)
):
    try:
        if file_id:
            file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
            actual_file_id = await utils.save_upload_file(file, file_id)
        else:
            actual_file_id = await utils.save_upload_file(file)
        
        return {"file_id": actual_file_id}
    except Exception as e:
        raise HTTPException(500, f"上传失败: {str(e)}")

@app.websocket("/ws/{file_id}")
async def websocket_endpoint(ws: WebSocket, file_id: str):
    await websocket.handle_websocket(ws, file_id)

@app.post("/extract-audio/{file_id}")
async def extract_audio_endpoint(file_id: str):
    return await audio.extract_audio(file_id)

@app.post("/api/generate_subtitles")
async def generate_subtitles_endpoint(
    file_id: str = Body(...),
    language: str = Body("zh"),
    model_type: str = Body("whisper_tiny")
):
    try:
        # 获取音频文件路径
        audio_file_id = os.path.splitext(file_id)[0] + '.mp3'
        audio_path = AUDIO_DIR / audio_file_id
        if not audio_path.exists():
            raise HTTPException(404, f"音频文件不存在: {audio_path}")

        print(f"处理字幕生成请求 - 文件: {file_id}, 语言: {language}, 模型: {model_type}")

        # 生成字幕
        result = await subtitles.generate_subtitles(
            file_id=file_id,
            audio_path=audio_path,
            model_type=model_type,
            language=language
        )

        return {
            "status": "success",
            "message": "字幕生成成功",
            "subtitles": result
        }

    except Exception as e:
        print(f"字幕生成失败: {str(e)}")
        if isinstance(e, HTTPException):
            raise
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

@app.post("/generate-speech/{file_id}")
async def generate_speech_endpoint(
    file_id: str,
    params: dict = Body(...),
):
    try:
        return await speech.generate_speech_for_file(
            file_id,
            target_language=params.get('target_language'),
            voice_name=params.get('voice_name'),
            use_local_tts=params.get('use_local_tts', False)
        )
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/generate-speech-single/{file_id}/{subtitle_index}")
async def generate_speech_single_endpoint(
    file_id: str, 
    subtitle_index: int,
    text: str,
    voice_name: str = "zh-CN-XiaoxiaoNeural",
    target_language: str = "en-US",
    speed: float = 1.0
):
    return await speech.generate_speech(file_id, subtitle_index, text, voice_name, target_language, speed)

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
    return await subtitles.update_single_subtitle(
        data.get("file_id"), 
        data.get("index"), 
        data.get("text")
    )

@app.post("/merge-bilingual-subtitles/{file_id}")
async def merge_bilingual_subtitles_endpoint(
    file_id: str,
    source_language: str,
    target_language: str
):
    return await subtitles.merge_bilingual_subtitles(file_id, source_language, target_language)

@app.get("/export-subtitles/{file_id}")
async def export_subtitles_endpoint(
    file_id: str,
    target_language: str = None
):
    """导出字幕为SRT格式"""
    try:
        result = await subtitles.save_subtitles_as_srt(file_id, target_language)
        
        # 如果只有一个文件，直接返回
        if len(result["files"]) == 1:
            srt_file = result["files"][0]
            srt_path = Path(srt_file["file_path"])
            
            # 确保文件存在
            if not srt_path.exists():
                raise HTTPException(500, f"SRT文件不存在: {srt_path}")
            
            try:
                return FileResponse(
                    path=str(srt_path),  # 转换为字符串
                    filename=srt_file["filename"],
                    media_type="text/srt"
                )
            finally:
                # 延迟清理文件
                async def cleanup():
                    await asyncio.sleep(1)  # 等待文件发送完成
                    try:
                        if srt_path.exists():
                            srt_path.unlink()
                    except Exception as e:
                        print(f"清理文件失败: {e}")
                
                asyncio.create_task(cleanup())
        
        # 如果有多个文件，创建zip文件
        zip_path = TEMP_DIR / f"{file_id}_subtitles.zip"
        
        # 确保临时目录存在
        TEMP_DIR.mkdir(exist_ok=True)
        
        # 创建 zip 文件
        try:
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for srt_file in result["files"]:
                    srt_path = Path(srt_file["file_path"])
                    if srt_path.exists():
                        zipf.write(
                            srt_path, 
                            srt_file["filename"]
                        )
            
            # 确保 zip 文件已经创建
            if not zip_path.exists():
                raise HTTPException(500, "创建 ZIP 文件失败")
            
            # 返回 zip 文件
            try:
                return FileResponse(
                    path=str(zip_path),
                    filename=f"{file_id}_subtitles.zip",
                    media_type="application/zip"
                )
            finally:
                # 延迟清理所有文件
                async def cleanup():
                    await asyncio.sleep(1)  # 等待文件发送完成
                    try:
                        # 清理 SRT 文件
                        for srt_file in result["files"]:
                            srt_path = Path(srt_file["file_path"])
                            if srt_path.exists():
                                srt_path.unlink()
                        
                        # 清理 ZIP 文件
                        if zip_path.exists():
                            zip_path.unlink()
                    except Exception as e:
                        print(f"清理文件失败: {e}")
                
                asyncio.create_task(cleanup())
                
        except Exception as e:
            # 清理所有临时文件
            for srt_file in result["files"]:
                try:
                    Path(srt_file["file_path"]).unlink(missing_ok=True)
                except Exception:
                    pass
            
            if zip_path.exists():
                try:
                    zip_path.unlink()
                except Exception:
                    pass
            raise
                
    except Exception as e:
        # 确保出错时也清理文件
        if 'result' in locals():
            for srt_file in result["files"]:
                try:
                    Path(srt_file["file_path"]).unlink(missing_ok=True)
                except Exception:
                    pass
        
        if 'zip_path' in locals() and zip_path.exists():
            try:
                zip_path.unlink()
            except Exception:
                pass
            
        raise HTTPException(
            status_code=500,
            detail=f"导出字幕失败: {str(e)}"
        )




@app.post("/translate-single/{file_id}")
async def translate_single_subtitle_endpoint(
    file_id: str,
    request: SingleTranslationRequest
):
    return await translation.translate_single_subtitle(
        file_id=file_id,
        index=request.index,
        text=request.text,
        source_language=request.source_language,
        target_language=request.target_language
    )

@app.post("/generate-single-speech/{file_id}")
async def generate_single_speech_endpoint(
    file_id: str,
    request: SingleSpeechRequest
):
    print('The speed is {0}'.format(request.speed))
    return await speech.generate_speech_single(
        file_id=file_id,
        index=request.index,
        target_language=request.target_language,
        use_local_tts=request.use_local_tts,
        voice_name=request.voice_name,
        speed=request.speed
    )


# 添加新的请求模型
class SubtitleUploadRequest(BaseModel):
    file_id: str
    subtitles: list[dict]

@app.post("/upload-subtitles")
async def upload_subtitles_endpoint(data: SubtitleUploadRequest):
    """处理字幕上传请求"""
    try:
        file_id = data.file_id
        subtitles_data = data.subtitles

        # 确保字幕目录存在
        file_id_without_ext = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        
        # 保存字幕数据
        with open(subtitle_path, "w", encoding="utf-8") as f:
            json.dump(subtitles_data, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "message": "字幕上传成功",
            "file_id": file_id
        }

    except Exception as e:
        print(f"字幕上传失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"字幕上传失败: {str(e)}"
        )