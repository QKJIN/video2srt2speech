import subprocess
from fastapi import HTTPException
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from .config import (
    AUDIO_DIR, 
    UPLOAD_DIR, 
    TEMP_DIR, 
    MERGED_DIR,
    SUBTITLE_DIR
)
import asyncio
import json
from dataclasses import dataclass, asdict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def extract_audio(file_id: str):
    try:
        video_path = UPLOAD_DIR / file_id
        if not video_path.exists():
            raise HTTPException(404, "视频文件未找到")
            
        audio_file_id = Path(file_id).stem + '.mp3'
        final_audio_path = AUDIO_DIR / audio_file_id
        
        try:
            subprocess.run([
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vn',
                '-acodec', 'libmp3lame',
                '-ac', '1',
                '-ar', '16000',
                '-q:a', '4',
                str(final_audio_path)
            ], check=True)
            
            return {"message": "音频提取成功", "audio_file": audio_file_id}
            
        except Exception as e:
            final_audio_path.unlink(missing_ok=True)
            raise e
            
    except Exception as e:
        raise HTTPException(500, f"音频提取失败: {str(e)}")

async def extract_audio_segment(audio_path: Path, output_path: Path, start_time: float, end_time: float):
    """从音频文件中提取指定时间段的音频"""
    try:
        print(f"提取音频段: {start_time}s - {end_time}s -> {output_path}")
        
        if not audio_path.exists():
            raise HTTPException(500, f"源音频文件不存在: {audio_path}")

        # 直接使用一步转换，简化处理过程
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y',
            '-i', str(audio_path),
            '-ss', str(start_time),
            '-t', str(end_time - start_time),
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            '-f', 'wav',
            '-sample_fmt', 's16',  # 确保16位采样
            '-flags', '+bitexact',  # 使用精确模式
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"音频转换失败: {stderr.decode()}")
            raise Exception(stderr.decode())

        # 验证输出文件
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception("输出文件无效")

        print(f"音频段提取成功: {output_path}")
        return True
            
    except Exception as e:
        print(f"提取音频段失败: {str(e)}")
        if output_path.exists():
            output_path.unlink()
        raise HTTPException(500, f"提取音频段失败: {str(e)}") 
    

@dataclass
class DurationWarning:
    index: int
    audio_duration: float
    subtitle_duration: float
    diff_percent: float

class AudioProcessingError(Exception):
    """Custom exception for audio processing errors"""
    pass

def get_audio_duration(file_path: Path) -> float:
    """Get the duration of an audio file using ffprobe."""
    try:
        output = subprocess.check_output([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(file_path)
        ]).decode().strip()
        return float(output)
    except subprocess.CalledProcessError as e:
        raise AudioProcessingError(f"Failed to get audio duration: {str(e)}")

def create_silence(output_path: Path, duration: float) -> None:
    """Create a silent audio file of specified duration."""
    try:
        subprocess.run([
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', f'anullsrc=r={AudioConfig.SAMPLE_RATE}:cl=mono',
            '-t', str(duration),
            '-acodec', 'pcm_s16le',
            str(output_path)
        ], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise AudioProcessingError(f"Failed to create silence: {e.stderr}")

def process_audio_file(
    audio_file: Path,
    subtitle: Dict[str, Any],
    batch_start: float,
    batch_duration: float,
    global_index: int
) -> Optional[Tuple[str, float, Path]]:  # Modified return type to include audio file
    """Process a single audio file and return its filter command, duration, and file path."""
    try:
        logger.info(f"\nProcessing subtitle {global_index:04d}")
        logger.info(f"Subtitle content: {subtitle.get('text', '')}")
        logger.info(f"Subtitle timing: {subtitle['start']:.3f} -> {subtitle['start'] + subtitle['duration']:.3f}")
        logger.info(f"Checking audio file: {audio_file}")

        if not audio_file.exists():
            logger.warning(f"❌ Audio file not found: {audio_file}")
            return None

        file_size = audio_file.stat().st_size
        logger.info(f"Found audio file {global_index:04d}.mp3")

        audio_duration = get_audio_duration(audio_file)
        target_duration = float(subtitle['duration'])
        relative_start = float(subtitle['start']) - batch_start

        logger.info(f"✅ Processing audio:")
        logger.info(f"  - File size: {file_size/1024:.1f}KB")
        logger.info(f"  - Original duration: {audio_duration:.3f}s")
        logger.info(f"  - Target duration: {target_duration:.3f}s")
        logger.info(f"  - Relative start time: {relative_start:.3f}s")

        filter_cmd = (
            f'volume={AudioConfig.VOLUME_ADJUSTMENT},'
            f'atrim=0:{target_duration},'
            f'asetpts=PTS-STARTPTS,'
            f'adelay={int(relative_start*1000)}|{int(relative_start*1000)},'
            f'apad=whole_dur={batch_duration}'
        )

        logger.info("  - Filter command created successfully")
        return filter_cmd, audio_duration, audio_file

    except Exception as e:
        logger.error(f"❌ Failed to process audio file {audio_file}: {str(e)}")
        return None
    
async def merge_audio(file_id: str, target_language: str, include_original: bool = True, volume: float = 1.0):
    try:
        # 验证目录和文件
        audio_dir = AUDIO_DIR / file_id / target_language
        if not audio_dir.exists():
            raise HTTPException(404, "音频文件目录未找到")
            
        # 获取原始音频文件路径
        original_audio = AUDIO_DIR / f"{Path(file_id).stem}.mp3"
        if not original_audio.exists():
            logger.warning("原始音频文件不存在，将只合并生成的语音")

        # 加载字幕文件
        file_id_without_ext = Path(file_id).stem
        subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
        if not subtitle_file.exists():
            subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件未找到")
            
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)
            
        # 获取总时长
        subtitles.sort(key=lambda x: float(x['start']))
        total_duration = float(subtitles[-1]['start']) + float(subtitles[-1]['duration'])
            
        # 创建输出目录
        output_dir = MERGED_DIR / file_id
        output_dir.mkdir(parents=True, exist_ok=True)
        final_output = output_dir / f"{target_language}.mp3"

        # 初始化列表和计数器
        valid_audio_count = 0
        duration_warnings = []
        processed_files = []
        inputs = []
        filter_parts = []
        input_files = []  # 新增：用于���储有效的音频文件

        # 首先收集所有有效的频文件
        for i, subtitle in enumerate(subtitles):
            audio_file = audio_dir / f"{i:04d}.mp3"
            if audio_file.exists():
                try:
                    audio_duration = get_audio_duration(audio_file)
                    target_duration = float(subtitle['duration'])
                    start_time = float(subtitle["start"])
                    
                    logger.info(f"\n处理音频 {i:04d}:")
                    logger.info(f"- 开始时间: {start_time}s")
                    logger.info(f"- 目标时长: {target_duration}s")
                    logger.info(f"- 实际时长: {audio_duration}s")
                    
                    # 添加到输入文件列表
                    input_files.append((audio_file, start_time, target_duration))
                    processed_files.append(str(audio_file))
                    
                except Exception as e:
                    logger.error(f"处理音频文件失败 {audio_file}: {str(e)}")
                    continue

        if input_files:
            # 构建 FFmpeg 命令
            cmd = ['ffmpeg', '-y']
            
            # 添加所有输入文件
            for audio_file, _, _ in input_files:
                cmd.extend(['-i', str(audio_file)])
                
            # 添加原始音频文件（如果存在）
            has_original_audio = original_audio.exists()
            if has_original_audio:
                cmd.extend(['-i', str(original_audio)])
            
            # 构建过滤器命令
            filter_parts = []

            for i, (_, start_time, target_duration) in enumerate(input_files):
                # 获取当前音频文件的实际时长
                current_audio = input_files[i][0]
                actual_duration = get_audio_duration(current_audio)
                
                # 计算到下一个字幕的间隔时间
                next_start = input_files[i + 1][1] if i + 1 < len(input_files) else total_duration
                available_gap = next_start - (start_time + target_duration)
                
                # 决定最终使用的音频时长
                if actual_duration > target_duration and available_gap > 0:
                    # 如果音频超长且有间隔时间，使用实际音频时长和可用间隔中的较小值
                    final_duration = min(actual_duration, target_duration + available_gap)
                else:
                    # 否则使用目标时长
                    final_duration = target_duration
                
                filter_parts.append(
                    f'[{i}:a]'
                    f'atrim=0:{final_duration},'  # 使用计算后的最终时长
                    f'adelay={int(start_time*1000)}|{int(start_time*1000)}:all=1'
                    f'[delayed{i}];'
                )
                
                logger.info(f"处理音频 {i}:")
                logger.info(f"- 开始时间: {start_time:.3f}s")
                logger.info(f"- 目标时长: {target_duration:.3f}s")
                logger.info(f"- 实际时长: {actual_duration:.3f}s")
                logger.info(f"- 可用间隔: {available_gap:.3f}s")
                logger.info(f"- 最终时长: {final_duration:.3f}s")


            # 合并所有音频轨道
            filter_complex = ''.join(filter_parts)
            
            # 处理原始音频（如果存在且用户选择包含）
            if has_original_audio and include_original:
                # 先混合所有语音轨道
                merge_cmd = ''.join(f'[delayed{i}]' for i in range(len(input_files)))
                filter_complex += f'{merge_cmd}amix=inputs={len(input_files)}:dropout_transition=0[speech];'  # 混合语音轨道
                # 调整原始音频音量
                filter_complex += f'[{len(input_files)}:a]volume={volume}[bg];'  # 使用传入的volume参数调整背景音量
                # 混合语音和背景音频
                filter_complex += '[speech]volume=2[speech_adjusted];'  # 调整语音音量
                filter_complex += '[speech_adjusted][bg]amix=inputs=2:duration=first[premix];'
                filter_complex += '[premix]loudnorm=I=-16:TP=-1.5:LRA=11[aout]'  # 添加 loudnorm 滤镜
            else:
                # 如果没有原始音频，直接合并语音轨道
                merge_cmd = ''.join(f'[delayed{i}]' for i in range(len(input_files)))
                filter_complex += f'{merge_cmd}amix=inputs={len(input_files)}:dropout_transition=0,'
                filter_complex += 'loudnorm=I=-16:TP=-1.5:LRA=11[aout]'  # 添加 loudnorm 滤镜
            
            # 完成命令构建
            cmd.extend([
                '-filter_complex', filter_complex,
                '-map', '[aout]',
                '-t', str(total_duration),
                '-codec:a', 'libmp3lame',
                '-q:a', '2',
                str(final_output)
            ])
            
            # 执行命令
            logger.info("\n执行FFmpeg命令:")
            logger.info(' '.join(cmd))
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg合并失败: {result.stderr}")
                raise AudioProcessingError(f"音频合并失败: {result.stderr}")
            
            # 验证最终文件
            if not final_output.exists():
                raise AudioProcessingError("最终文件未生成")
            
            final_duration = get_audio_duration(final_output)
            logger.info(f"合并完成! 最终文件: {final_output}")
            logger.info(f"最终时长: {final_duration:.2f}秒")
            
            return {
                "merged_file": f"{file_id}/{target_language}.mp3",
                "duration_warnings": [asdict(w) for w in duration_warnings] if duration_warnings else None,
                "processed_files": len(processed_files),
                "total_files": len(subtitles),
                "final_duration": round(final_duration, 2)
            }
        else:
            raise HTTPException(500, "没有找到可合并的音频文件")
            
    except Exception as e:
        logger.error(f"音频合并失败: {str(e)}")
        if final_output.exists():
            final_output.unlink()
        raise HTTPException(500, str(e))