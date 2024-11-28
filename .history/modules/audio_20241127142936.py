import subprocess
from fastapi import HTTPException
from pathlib import Path
from .config import (
    AUDIO_DIR, 
    UPLOAD_DIR, 
    TEMP_DIR, 
    MERGED_DIR,
    SUBTITLE_DIR
)
import asyncio
import json

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

async def merge_audio(file_id: str, target_language: str):
    try:
        audio_dir = AUDIO_DIR / file_id / target_language
        if not audio_dir.exists():
            raise HTTPException(404, "音频文件目录未找到")
            
        # 读取字幕文件以获取时间信息
        file_id_without_ext = Path(file_id).stem
        subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
        if not subtitle_file.exists():
            subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件未找到")
            
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)
            
        # 获取最后一个字幕的结束时间作为总时长
        last_subtitle = subtitles[-1]
        total_duration = last_subtitle['start'] + last_subtitle['duration']
            
        # 创建输出目录
        output_dir = MERGED_DIR / file_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{target_language}.mp3"
        
        # 创建一个临时的完整音频文件（全是静音）
        temp_base = TEMP_DIR / f"{file_id}_base.wav"
        subprocess.run([
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', f'anullsrc=r=16000:cl=mono',
            '-t', str(total_duration),
            '-acodec', 'pcm_s16le',
            str(temp_base)
        ], check=True)

        # 创建复杂的filter_complex命令
        inputs = ['-i', str(temp_base)]
        filter_parts = []
        for i, subtitle in enumerate(subtitles):
            audio_file = audio_dir / f"{i:04d}.mp3"
            if audio_file.exists():
                inputs.extend(['-i', str(audio_file)])
                # 获取音频时长
                duration = float(subprocess.check_output([
                    'ffprobe', '-v', 'error',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(audio_file)
                ]).decode().strip())
                
                start_time = float(subtitle['start'])
                filter_parts.append(
                    f'[{i+1}:a]adelay={int(start_time*1000)}|{int(start_time*1000)}[aud{i}];'
                )
                
        # 构建混音命令
        if filter_parts:
            filter_parts.append('[0:a]')  # 添加基础静音轨道
            for i in range(len(subtitles)):
                if (audio_dir / f"{i:04d}.mp3").exists():
                    filter_parts.append(f'[aud{i}]')
            filter_parts.append(f'amix=inputs={len(filter_parts)}:duration=first:dropout_transition=0[aout]')
            
            filter_complex = ''.join(filter_parts)
            
            # 执行最终的合并命令
            cmd = [
                'ffmpeg', '-y'
            ] + inputs + [
                '-filter_complex', filter_complex,
                '-map', '[aout]',
                '-codec:a', 'libmp3lame',
                '-q:a', '4',
                str(output_path)
            ]
            
            print(f"执行合并命令: {' '.join(cmd)}")
            
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if process.returncode != 0:
                print(f"FFmpeg错误输出: {process.stderr}")
                raise Exception(f"FFmpeg命令执行失败: {process.stderr}")
            
            # 验证最终文件的时长
            final_duration = float(subprocess.check_output([
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(output_path)
            ]).decode().strip())
            
            print(f"合并后的音频时长: {final_duration:.2f}秒，预期时长: {total_duration:.2f}秒")
            
            return {"merged_file": f"{file_id}/{target_language}.mp3"}
        else:
            raise HTTPException(500, "没有找到任何音频文件可以合并")
            
    except Exception as e:
        print(f"合并音频失败: {str(e)}")
        raise HTTPException(500, str(e))
    finally:
        # 清理临时文件
        if 'temp_base' in locals() and temp_base.exists():
            temp_base.unlink()

async def extract_audio_segment(audio_path: Path, output_path: Path, start_time: float, end_time: float):
    """从音频文件中提取指定时间段的音频"""
    try:
        print(f"提取音频段: {start_time}s - {end_time}s -> {output_path}")
        
        # 确保输入文件存在
        if not audio_path.exists():
            raise HTTPException(500, f"源音频文件不存在: {audio_path}")
        
        # 运行ffmpeg命令，添加音频预处理
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y',
            '-i', str(audio_path),
            '-ss', str(start_time),
            '-t', str(end_time - start_time),
            # 添加降噪
            '-af', 'anlmdn=s=7:p=0.002:r=0.01,highpass=f=200,lowpass=f=3000',
            '-acodec', 'pcm_s16le',  # WAV格式
            '-ar', '16000',          # 16kHz采样率
            '-ac', '1',              # 单声道
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg错误输出: {stderr.decode()}")
            raise HTTPException(500, f"音频段提取失败: {stderr.decode()}")
        
        if not output_path.exists():
            raise HTTPException(500, "音频段提取失败：输出文件未生成")
            
        # 验证输出文件大小
        if output_path.stat().st_size == 0:
            raise HTTPException(500, "音频段提取失败：输出文件为空")
            
        print(f"音频段提取成功: {output_path}")
            
    except Exception as e:
        print(f"提取音频段失败: {str(e)}")
        raise HTTPException(500, f"提取音频段失败: {str(e)}") 