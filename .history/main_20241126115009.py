from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uuid
import os
from modules import config, websocket, subtitles, audio
from modules.config import DIRS, UPLOAD_DIR

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

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # 文件上传处理逻辑...

@app.websocket("/ws/{file_id}")
async def websocket_endpoint(websocket: WebSocket, file_id: str):
    await websocket.handle_websocket(websocket, file_id)

# 其他路由处理...
