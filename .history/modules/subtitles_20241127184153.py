import json
import os
from fastapi import HTTPException
import aiofiles
from pathlib import Path
import math
import asyncio
from . import speech, audio, video, websocket
from .config import (
    TEMP_DIR, 
    SUBTITLE_DIR, 
    AUDIO_DIR, 
    UPLOAD_DIR,
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION
)
from .utils import convert_to_srt
import re
import azure.cognitiveservices.speech as speechsdk

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
    try:
        print(f"开始生成字幕，文件ID: {file_id}")
        
        # 构建音频文件路径（使用.mp3扩展名）
        audio_file_id = os.path.splitext(file_id)[0] + '.mp3'
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
        
        async def process_segment(segment_index: int):
            start_time = segment_index * segment_duration
            end_time = min((segment_index + 1) * segment_duration, video_duration)
            
            # 创建临时音频段文件
            segment_path = TEMP_DIR / f"{audio_file_id}_segment_{segment_index}.wav"
            
            try:
                # 提取音频段
                await audio.extract_audio_segment(audio_path, segment_path, start_time, end_time)
                
                # 存储当前段的识别结果
                segment_results = []
                recognition_complete = asyncio.Event()

                def calculate_progress(current_time):
                    """计算总体进度"""
                    previous_segments_progress = (segment_index * segment_duration) / video_duration
                    current_segment_progress = (current_time - start_time) / video_duration
                    total_progress = (previous_segments_progress + current_segment_progress) * 100
                    return min(100, int(total_progress))

                def handle_result(evt):
                    try:
                        if evt.result.text:
                            print(f"段落 {segment_index} 识别到文本: {evt.result.text}")
                            duration = evt.result.duration / 10000000
                            start_time_in_video = start_time + (evt.result.offset / 10000000)
                            
                            # 根据标点符号分割句子
                            sentences = re.split('[。！？.!?]', evt.result.text)
                            sentences = [s.strip() for s in sentences if s.strip()]
                            
                            if len(sentences) > 1:
                                # 处理多个句子
                                total_chars = sum(len(s) for s in sentences)
                                current_start = start_time_in_video
                                
                                for sentence in sentences:
                                    if not sentence:
                                        continue
                                    
                                    sentence_ratio = len(sentence) / total_chars
                                    sentence_duration = duration * sentence_ratio
                                    optimal_duration = max(2.0, min(sentence_duration, 10.0))
                                    
                                    segment_results.append({
                                        "start": current_start,
                                        "duration": optimal_duration,
                                        "text": sentence
                                    })
                                    print(f"段落 {segment_index} 添加字幕: {sentence} (时长: {optimal_duration:.2f}秒)")
                                    current_start += optimal_duration
                            else:
                                optimal_duration = max(2.0, min(duration, 10.0))
                                segment_results.append({
                                    "start": start_time_in_video,
                                    "duration": optimal_duration,
                                    "text": evt.result.text
                                })
                                print(f"段落 {segment_index} 添加字幕: {evt.result.text} (时长: {optimal_duration:.2f}秒)")
                            
                            # 发送进度更新
                            progress = calculate_progress(start_time_in_video)
                            loop = asyncio.get_running_loop()
                            loop.create_task(websocket.send_message(file_id, {
                                "type": "progress",
                                "text": evt.result.text,
                                "progress": progress
                            }))
                    except Exception as e:
                        print(f"处理识别结果时出错: {str(e)}")
                        recognition_errors.append(str(e))

                def handle_completed(evt):
                    try:
                        print(f"段落 {segment_index} 语音识别完成")
                        recognition_complete.set()
                    except Exception as e:
                        print(f"段落 {segment_index} 处理完成事件时出错: {str(e)}")
                        recognition_errors.append(str(e))

                def handle_canceled(evt):
                    try:
                        print(f"段落 {segment_index} 语音识别被取消: {evt.result.cancellation_details.reason}")
                        print(f"错误详情: {evt.result.cancellation_details.error_details}")
                        recognition_complete.set()
                    except Exception as e:
                        print(f"段落 {segment_index} 处理取消事件时出错: {str(e)}")
                        recognition_errors.append(str(e))

                # 配置语音识别
                speech_config = speechsdk.SpeechConfig(
                    subscription=AZURE_SPEECH_KEY, 
                    region=AZURE_SPEECH_REGION
                )
                
                if language.lower() == "en":
                    speech_config.speech_recognition_language = "en-US"
                else:
                    speech_config.speech_recognition_language = language

                # 设置详细日志
                speech_config.set_property(
                    speechsdk.PropertyId.Speech_LogFilename, 
                    str(TEMP_DIR / f"azure_speech_{file_id}_segment_{segment_index}.log")
                )
                
                # 优化语音识别参数
                speech_config.set_property_by_name(
                    "SpeechServiceConnection_InitialSilenceTimeoutMs", "2000"
                )
                speech_config.set_property_by_name(
                    "SpeechServiceConnection_EndSilenceTimeoutMs", "1000"
                )
                speech_config.set_property_by_name(
                    "SpeechServiceConnection_SegmentationMode", "SentenceBoundary"
                )
                
                speech_config.enable_audio_logging = True

                # 配置音频输入
                audio_config = speechsdk.AudioConfig(filename=str(segment_path))
                speech_recognizer = speechsdk.SpeechRecognizer(
                    speech_config=speech_config, 
                    audio_config=audio_config
                )

                # 注册事件处理函数
                speech_recognizer.recognized.connect(handle_result)
                speech_recognizer.session_stopped.connect(handle_completed)
                speech_recognizer.canceled.connect(handle_canceled)

                # 开始识别
                speech_recognizer.start_continuous_recognition()
                
                try:
                    # 等待识别完成，设置超时
                    timeout = (end_time - start_time) * 2
                    await asyncio.wait_for(recognition_complete.wait(), timeout=timeout)
                    print(f"段落 {segment_index} 处理完成，识别到 {len(segment_results)} 条字幕")
                except asyncio.TimeoutError:
                    print(f"段落 {segment_index} 语音识别超时")
                    recognition_errors.append(f"段落 {segment_index} 识别超时")
                finally:
                    speech_recognizer.stop_continuous_recognition()
                    await asyncio.sleep(1)  # 添加短暂延迟确保资源释放
                
                return segment_results

            except Exception as e:
                error_msg = f"处理音频段 {segment_index} 时出错: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
                return []
            finally:
                if segment_path.exists():
                    segment_path.unlink()

        # 并行处理所有音频段
        tasks = [process_segment(i) for i in range(total_segments)]
        segment_results = await asyncio.gather(*tasks)

        # 合并所有段落的结果
        for results in segment_results:
            all_subtitles.extend(results)

        # 按开始时间排序
        all_subtitles.sort(key=lambda x: x["start"])

        # 处理错误和保存结果
        if recognition_errors and all_subtitles:
            print("生成字幕时发生一些错误，但仍然返回部分结果")
            print("错误信息:", "\n".join(recognition_errors))

        if not all_subtitles:
            error_msg = "未能生成任何字幕\n" + "\n".join(recognition_errors)
            raise HTTPException(500, error_msg)

        # 保存字幕文件
        file_id_without_ext = os.path.splitext(file_id)[0]
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        with open(subtitle_path, "w", encoding="utf-8") as f:
            json.dump(all_subtitles, f, ensure_ascii=False, indent=2)
        
        await websocket.send_message(file_id, {
            "type": "complete",
            "message": "字幕生成完成"
        })
        
        return all_subtitles

    except Exception as e:
        error_msg = f"生成字幕时出错: {str(e)}"
        print(error_msg)
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

async def save_subtitles_as_srt(file_id: str, language: str = None):
    """导出字幕为SRT格式"""
    try:
        file_id_without_ext = os.path.splitext(file_id)[0]
        
        # 确定要导出的字幕文件
        subtitle_files = []
        
        # 原始字幕
        original_subtitle = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        if original_subtitle.exists():
            subtitle_files.append(("original", original_subtitle))
        
        # 翻译字幕（如果存在）
        if language:
            translated_subtitle = SUBTITLE_DIR / f"{file_id_without_ext}_{language}.json"
            if translated_subtitle.exists():
                subtitle_files.append((language, translated_subtitle))
        
        if not subtitle_files:
            raise HTTPException(404, "未找到字幕文件")
        
        # 转换并返回所有字幕文件
        srt_files = []
        for lang, subtitle_file in subtitle_files:
            # 读取JSON字幕
            with open(subtitle_file, 'r', encoding='utf-8') as f:
                subtitles = json.load(f)
            
            # 转换为SRT格式
            srt_content = convert_to_srt(subtitles)
            
            # 创建临时SRT文件
            temp_srt = TEMP_DIR / f"{file_id_without_ext}_{lang}.srt"
            with open(temp_srt, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            srt_files.append({
                "language": lang,
                "file_path": str(temp_srt),
                "filename": f"{file_id_without_ext}_{lang}.srt"
            })
        
        return {
            "status": "success",
            "files": srt_files
        }
        
    except Exception as e:
        raise HTTPException(500, f"导出SRT字幕失败: {str(e)}")