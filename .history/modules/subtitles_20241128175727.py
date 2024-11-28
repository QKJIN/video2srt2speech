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

async def update_subtitle(file_id: str, data: dict):
    """更新字幕内容"""
    try:
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        try:
            # 读取字幕文件
            async with aiofiles.open(subtitle_file, "r", encoding="utf-8") as f:
                content = await f.read()
                subtitles = json.loads(content)

            # 检查索引是否有效
            index = data.get("index")
            new_text = data.get("text")
            
            if index is None or new_text is None:
                raise HTTPException(400, "缺少必要的参数")
            
            if not isinstance(subtitles, list):
                raise HTTPException(400, "无效的字幕文件格式")
            
            if index < 0 or index >= len(subtitles):
                raise HTTPException(400, "无效的字幕索引")

            # 更新字幕文本
            subtitles[index]["text"] = new_text

            # 写入更新后的字幕
            async with aiofiles.open(subtitle_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(subtitles, ensure_ascii=False, indent=2))

            return {
                "status": "success",
                "message": "字幕更新成功",
                "index": index,
                "text": new_text
            }

        except json.JSONDecodeError:
            raise HTTPException(500, "字幕文件格式错误")
        except IOError as e:
            raise HTTPException(500, f"文件读写错误: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"更新字幕失败: {str(e)}")
        raise HTTPException(500, f"更新字幕失败: {str(e)}")

async def update_single_subtitle(file_id: str, index: int, new_text: str):
    """更新单个字幕"""
    if not isinstance(index, int):
        raise HTTPException(400, "字幕索引必须是整数")
    if not isinstance(new_text, str):
        raise HTTPException(400, "字幕文本必须是字符串")
        
    return await update_subtitle(file_id, {
        "index": index,
        "text": new_text
    })

async def generate_subtitles(
    file_id: str, 
    language: str = "zh-CN", 
    use_whisper: bool = False,
    whisper_model_size: str = None,
    auto_fallback: bool = True
):
    """生成字幕的主要逻辑"""
    try:
        print(f"开始生成字幕，文件ID: {file_id}")
        print(f"参数 - 语言: {language}, 使用Whisper: {use_whisper}, 模型大小: {whisper_model_size}")
        
        # 获取音频文件路径
        audio_file_id = os.path.splitext(file_id)[0] + '.mp3'
        audio_path = AUDIO_DIR / audio_file_id
        video_path = UPLOAD_DIR / file_id
        
        if not audio_path.exists():
            print(f"音频文件不存在: {audio_path}")
            raise HTTPException(404, "音频文件未找到，请先提取音频")

        all_subtitles = []
        try:
            if use_whisper:
                # Whisper 处理逻辑
                from . import whisper_utils
                
                if whisper_model_size:
                    whisper_utils.set_model_size(whisper_model_size)
                
                await websocket.send_message(file_id, {
                    "type": "progress",
                    "message": "正在使用Whisper生成字幕",
                    "progress": 0
                })
                
                all_subtitles = await whisper_utils.transcribe_audio(audio_path, language)
                
                await websocket.send_message(file_id, {
                    "type": "progress",
                    "message": "Whisper字幕生成完成",
                    "progress": 100
                })
            else:
                # Azure 处理逻辑
                try:
                    print(f"开始处理音频文件: {audio_path}")
                    print(f"源语言: {language}")

                    # 获取视频时长
                    video_duration = video.get_video_duration(video_path)

                    # 将音频分段处理
                    segment_duration = 300  # 5分钟一段
                    total_segments = math.ceil(video_duration / segment_duration)
                    print(f"音频总时长: {video_duration}秒，分为 {total_segments} 段处理")

                    # 存储所有字幕和错误
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

                            def handle_result(evt):
                                try:
                                    if evt.result.text:
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
                                                current_start += optimal_duration
                                        else:
                                            optimal_duration = max(2.0, min(duration, 10.0))
                                            segment_results.append({
                                                "start": start_time_in_video,
                                                "duration": optimal_duration,
                                                "text": evt.result.text
                                            })

                                except Exception as e:
                                    print(f"处理识别结果时出错: {str(e)}")
                                    recognition_errors.append(str(e))

                            def handle_completed(evt):
                                recognition_complete.set()

                            def handle_canceled(evt):
                                print(f"语音识别被取消: {evt.result.cancellation_details.reason}")
                                print(f"错误详情: {evt.result.cancellation_details.error_details}")
                                recognition_complete.set()

                            # 配置语音识别
                            speech_config = speechsdk.SpeechConfig(
                                subscription=AZURE_SPEECH_KEY, 
                                region=AZURE_SPEECH_REGION
                            )
                            
                            if language.lower() == "en":
                                speech_config.speech_recognition_language = "en-US"
                            else:
                                speech_config.speech_recognition_language = language

                            audio_config = speechsdk.AudioConfig(filename=str(segment_path))
                            speech_recognizer = speechsdk.SpeechRecognizer(
                                speech_config=speech_config, 
                                audio_config=audio_config
                            )

                            speech_recognizer.recognized.connect(handle_result)
                            speech_recognizer.session_stopped.connect(handle_completed)
                            speech_recognizer.canceled.connect(handle_canceled)

                            speech_recognizer.start_continuous_recognition()
                            
                            try:
                                await asyncio.wait_for(recognition_complete.wait(), timeout=60)
                            finally:
                                speech_recognizer.stop_continuous_recognition()
                            
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

                    if not all_subtitles:
                        raise Exception("未能识别出任何文本")

                except Exception as azure_error:
                    if "Quota exceeded" in str(azure_error) and auto_fallback:
                        print("Azure 配额超限，自动切换到 Whisper")
                        await websocket.send_message(file_id, {
                            "type": "progress",
                            "message": "Azure 配额超限，切换到 Whisper",
                            "progress": 0
                        })
                        return await generate_subtitles(
                            file_id, 
                            language, 
                            use_whisper=True,
                            whisper_model_size="base",
                            auto_fallback=False
                        )
                    else:
                        raise

            # 保存字幕文件
            file_id_without_ext = os.path.splitext(file_id)[0]
            subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
            with open(subtitle_path, "w", encoding="utf-8") as f:
                json.dump(all_subtitles, f, ensure_ascii=False, indent=2)
            
            return all_subtitles

        except Exception as e:
            error_msg = f"字幕生成失败: {str(e)}"
            print(error_msg)
            await websocket.send_message(file_id, {
                "type": "error",
                "message": error_msg
            })
            raise HTTPException(500, error_msg)

    except Exception as e:
        error_msg = f"���成字幕时出错: {str(e)}"
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
    temp_files = []  # 用于跟踪创建的临时文件
    
    try:
        file_id_without_ext = os.path.splitext(file_id)[0]
        
        # 确保临时目录存在
        TEMP_DIR.mkdir(exist_ok=True)
        
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
        
        srt_files = []
        # 转换并返回所有字幕文件
        for lang, subtitle_file in subtitle_files:
            try:
                # 读取JSON字幕
                with open(subtitle_file, 'r', encoding='utf-8') as f:
                    subtitles = json.load(f)
                
                # 转换为SRT格式
                srt_content = convert_to_srt(subtitles)
                
                # 创建临时SRT文件
                temp_srt = TEMP_DIR / f"{file_id_without_ext}_{lang}.srt"
                temp_files.append(temp_srt)  # 添加到跟踪列表
                
                # 写入内容
                with open(temp_srt, 'w', encoding='utf-8') as f:
                    f.write(srt_content)
                
                # 验证文件是否成功创建
                if not temp_srt.exists():
                    raise HTTPException(500, f"创建SRT文件失败: {temp_srt}")
                
                srt_files.append({
                    "language": lang,
                    "file_path": str(temp_srt),
                    "filename": f"{file_id_without_ext}_{lang}.srt"
                })
                
            except Exception as e:
                print(f"处理字幕文件失败: {str(e)}")
                raise
        
        if not srt_files:
            raise HTTPException(500, "未能创建任何SRT文件")
        
        # 确保所有文件都存在
        for srt_file in srt_files:
            if not Path(srt_file["file_path"]).exists():
                raise HTTPException(500, f"SRT文件不存在: {srt_file['file_path']}")
        
        return {
            "status": "success",
            "files": srt_files
        }
        
    except Exception as e:
        # 清理所有临时文件
        for temp_file in temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception as cleanup_error:
                print(f"清理临时文件失败: {cleanup_error}")
        
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, f"导出SRT字幕失败: {str(e)}")