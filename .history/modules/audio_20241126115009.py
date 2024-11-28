import subprocess
from fastapi import HTTPException
from pathlib import Path
from .config import AUDIO_DIR, UPLOAD_DIR, TEMP_DIR, MERGED_DIR

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
            
        audio_files = sorted(list(audio_dir.glob("*.mp3")), key=lambda x: int(x.stem))
        if not audio_files:
            raise HTTPException(404, "未找到任何音频文件")
            
        output_dir = MERGED_DIR / file_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{target_language}.mp3"
        
        # 构建ffmpeg命令
        inputs = []
        filter_complex = []
        for i, audio_file in enumerate(audio_files):
            inputs.extend(['-i', str(audio_file)])
            filter_complex.append(f'[{i}:a]')
        
        filter_complex = ''.join(filter_complex) + f'concat=n={len(audio_files)}:v=0:a=1[outa]'
        
        command = [
            'ffmpeg', '-y',
            *inputs,
            '-filter_complex', filter_complex,
            '-map', '[outa]',
            '-codec:a', 'libmp3lame',
            '-q:a', '4',
            str(output_path)
        ]
        
        process = subprocess.run(command, capture_output=True, text=True)
        
        if process.returncode != 0:
            raise HTTPException(500, f"合并音频失败: {process.stderr}")
                
        return {"merged_file": f"{file_id}/{target_language}.mp3"}
            
    except Exception as e:
        raise HTTPException(500, str(e)) 