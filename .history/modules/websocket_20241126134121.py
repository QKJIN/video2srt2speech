from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect
import asyncio

# 存储WebSocket连接
active_connections: Dict[str, WebSocket] = {}

async def handle_websocket(websocket: WebSocket, file_id: str):
    """处理 WebSocket 连接"""
    try:
        await websocket.accept()
        active_connections[file_id] = websocket
        print(f"WebSocket连接已建立: {file_id}")
        
        try:
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                else:
                    print(f"收到WebSocket消息: {data}")
        except WebSocketDisconnect:
            print(f"WebSocket连接断开: {file_id}")
        except Exception as e:
            print(f"WebSocket错误: {str(e)}")
    except Exception as e:
        print(f"WebSocket连接建立失败: {str(e)}")
    finally:
        if file_id in active_connections:
            del active_connections[file_id]

async def send_message(file_id: str, message: dict):
    """发送 WebSocket 消息"""
    if file_id in active_connections:
        ws = active_connections[file_id]
        try:
            await ws.send_json(message)
            if message.get("type") in ["complete", "error"]:
                await asyncio.sleep(1)  # 等待1秒确保消息发送完成
                if file_id in active_connections:
                    await ws.close()
                    del active_connections[file_id]
        except Exception as e:
            print(f"发送WebSocket消息时出错: {str(e)}")
            if file_id in active_connections:
                del active_connections[file_id] 