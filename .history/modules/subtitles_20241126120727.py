import json
import os
from fastapi import HTTPException
import aiofiles
from pathlib import Path
import math
import asyncio
from . import speech, audio, video, websocket
from .config import TEMP_DIR, SUBTITLE_DIR, AUDIO_DIR, UPLOAD_DIR
from .utils import convert_to_srt  # 从 utils 导入

async def update_subtitle(file_id: str, index: int, new_text: str):
    try:
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        async with aiofiles.open(subtitle_file, "r", encoding="utf-8") as f:
            content = await f.read()
            subtitles = json.loads(content)

        if not isinstance(subtitles, list) or index >= len(subtitles):
            raise HTTPException(400, "无效的字幕索引")

        subtitles[index]["text"] = new_text

        async with aiofiles.open(subtitle_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(subtitles, ensure_ascii=False, indent=2))

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, f"更新字幕失败: {str(e)}")

async def generate_subtitles(file_id: str, language: str = "zh-CN"):
    """生成字幕的主要逻辑"""
    try:
        print(f"开始生成字幕，文件ID: {file_id}")
        
        # 获取音频文件路径
        audio_file_id = Path(file_id).stem + '.mp3'
        audio_path = AUDIO_DIR / audio_file_id
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

        # 处理所有音频段
        for i in range(total_segments):
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, video_duration)
            
            # 创建临时音频段
            segment_path = TEMP_DIR / f"{audio_file_id}_segment_{i}.wav"
            
            try:
                # 提取音频段
                await audio.extract_audio_segment(audio_path, segment_path, start_time, end_time)
                
                # 发送进度消息
                progress = (i / total_segments) * 50  # 前50%进度用于音频分段
                await websocket.send_message(file_id, {
                    "type": "progress",
                    "message": f"处理第 {i+1}/{total_segments} 段",
                    "progress": progress
                })

                # 识别语音
                segment_results = await speech.recognize_speech(file_id, segment_path, language)
                all_subtitles.extend(segment_results)
                
            except Exception as e:
                error_msg = f"处理音频段 {i} 时出错: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
            finally:
                # 在语音识别完成后再清理临时文件
                if segment_path.exists():
                    segment_path.unlink()

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