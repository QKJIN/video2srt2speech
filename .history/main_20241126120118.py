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
async def websocket_endpoint(websocket: WebSocket, file_id: str):
    await websocket.handle_websocket(websocket, file_id)

@app.post("/extract-audio/{file_id}")
async def extract_audio_endpoint(file_id: str):
    return await audio.extract_audio(file_id)

@app.post("/generate-subtitles/{file_id}")
async def generate_subtitles_endpoint(file_id: str, language: str = "zh-CN"):
    try:
        print(f"开始生成字幕，文件ID: {file_id}")
        
        # 获取音频文件路径
        audio_file_id = Path(file_id).stem + '.mp3'
        audio_path = config.AUDIO_DIR / audio_file_id
        video_path = UPLOAD_DIR / file_id
        
        if not audio_path.exists():
            print(f"音频文件不存在: {audio_path}")
            raise HTTPException(404, "音频文件未找到，请先提取音频")

        print(f"开始处理音频文件: {audio_path}")
        print(f"源语言: {language}")

        # 获取视频时长
        video_duration = video.get_video_duration(video_path)

        # 将音频分段处理
        segment_duration = 300  # 5分钟一段
        total_segments = math.ceil(video_duration / segment_duration)
        print(f"音频总时长: {video_duration}秒，分为 {total_segments} 段处理")

        # 存储所有字幕和错误
        all_subtitles = []
        recognition_errors = []

        # 发送开始消息
        await websocket.send_message(file_id, {
            "type": "progress",
            "message": "开始生成字幕",
            "progress": 0
        })

        # 并行处理所有音频段
        tasks = []
        for i in range(total_segments):
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, video_duration)
            
            # 创建临时音频段
            segment_path = config.TEMP_DIR / f"{audio_file_id}_segment_{i}.wav"
            
            try:
                # 提取音频段
                await audio.extract_audio_segment(audio_path, segment_path, start_time, end_time)
                
                # 添加识别任务
                task = speech.recognize_speech(file_id, segment_path, language)
                tasks.append(task)
                
                # 发送进度消息
                progress = (i / total_segments) * 50  # 前50%进度用于音频分段
                await websocket.send_message(file_id, {
                    "type": "progress",
                    "message": f"处理第 {i+1}/{total_segments} 段",
                    "progress": progress
                })
                
            except Exception as e:
                error_msg = f"处理音频段 {i} 时出错: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
            finally:
                # 确保清理临时文件
                segment_path.unlink(missing_ok=True)

        # 等待所有识别任务完成
        segment_results = await asyncio.gather(*tasks)

        # 合并所有段落的结果
        for results in segment_results:
            if results:  # 确保结果不为空
                all_subtitles.extend(results)

        # 按开始时间排序
        all_subtitles.sort(key=lambda x: x["start"])

        # 如果有错误但仍然有一些字幕，返回部分结果
        if recognition_errors and all_subtitles:
            print("生成字幕时发生一些错误，但仍然返回部分结果")
            print("错误信息:", "\n".join(recognition_errors))

        # 如果完全没有字幕，抛出错误
        if not all_subtitles:
            error_msg = "未能生成任何字幕\n" + "\n".join(recognition_errors)
            raise HTTPException(500, error_msg)

        # 保存字幕文件
        file_id_without_ext = Path(file_id).stem
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        with open(subtitle_path, "w", encoding="utf-8") as f:
            json.dump(all_subtitles, f, ensure_ascii=False, indent=2)
        
        # 发送完成消息
        await websocket.send_message(file_id, {
            "type": "complete",
            "message": "字幕生成完成",
            "progress": 100
        })
        
        return all_subtitles

    except Exception as e:
        error_msg = f"生成字幕时出错: {str(e)}"
        print(error_msg)
        # 发送错误消息
        await websocket.send_message(file_id, {
            "type": "error",
            "message": error_msg
        })
        raise HTTPException(500, error_msg)

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
