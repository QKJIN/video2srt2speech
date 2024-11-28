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

        # 获取视频时长
        video_duration = video.get_video_duration(video_path)

        # 将音频分段处理
        segment_duration = 30  # 减小到30秒
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

        # 处理每个音频段
        retry_delays = [0, 5, 10]  # 重试延迟时间
        for i in range(total_segments):
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, video_duration)
            
            # 创建临时音频段
            segment_path = TEMP_DIR / f"{audio_file_id}_segment_{i}.wav"
            
            try:
                # 提取音频段
                await audio.extract_audio_segment(audio_path, segment_path, start_time, end_time)
                
                # 识别语音，添加重试逻辑
                for retry_count, delay in enumerate(retry_delays):
                    if delay > 0:
                        print(f"等待 {delay} 秒后重试...")
                        await asyncio.sleep(delay)
                    
                    try:
                        results = await speech.recognize_speech(file_id, segment_path, language)
                        if results:
                            # 调整时间戳
                            for result in results:
                                result["start"] += start_time
                            all_subtitles.extend(results)
                            break  # 成功则退出重试循环
                    except Exception as e:
                        if "Quota exceeded" in str(e):
                            if retry_count < len(retry_delays) - 1:
                                print(f"配额限制，将进行第 {retry_count + 2} 次尝试")
                                continue
                        raise  # 重试次数用完或其他错误，抛出异常

                # 发送进度消息
                progress = min(95, (i + 1) / total_segments * 100)
                await websocket.send_message(file_id, {
                    "type": "progress",
                    "message": f"已完成 {i + 1}/{total_segments} 段识别",
                    "progress": progress
                })

            except Exception as e:
                error_msg = f"处理音频段 {i} 时出错: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
                # 如果是配额错误，等待更长时间
                if "Quota exceeded" in str(e):
                    print("检测到配额限制，等待30秒...")
                    await asyncio.sleep(30)
                    continue

            finally:
                # 清理临时文件
                if segment_path.exists():
                    segment_path.unlink()

            # 每段处理完后添加短暂延迟
            await asyncio.sleep(1)

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

async def merge_bilingual_subtitles(file_id: str, source_language: str, target_language: str):
    """合并双语字幕"""
    try:
        file_id_without_ext = Path(file_id).stem
        source_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        target_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"

        if not source_file.exists() or not target_file.exists():
            raise HTTPException(404, "源语言或目标语言字幕文件不存在")

        # 读取源语言字幕
        with open(source_file, 'r', encoding='utf-8') as f:
            source_subtitles = json.load(f)

        # 读取目标语言字幕
        with open(target_file, 'r', encoding='utf-8') as f:
            target_subtitles = json.load(f)

        if len(source_subtitles) != len(target_subtitles):
            raise HTTPException(500, "源语言和目标语言字幕数量不匹配")

        # 合并字幕
        bilingual_subtitles = []
        for src, tgt in zip(source_subtitles, target_subtitles):
            bilingual_subtitle = src.copy()
            bilingual_subtitle["text"] = f"{src['text']}\n{tgt['text']}"
            bilingual_subtitles.append(bilingual_subtitle)

        # 保存双语字幕
        output_file = SUBTITLE_DIR / f"{file_id_without_ext}_bilingual.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(bilingual_subtitles, f, ensure_ascii=False, indent=2)

        return {
            "message": "双语字幕合并成功",
            "subtitles": bilingual_subtitles
        }

    except Exception as e:
        raise HTTPException(500, f"合并双语字幕失败: {str(e)}")