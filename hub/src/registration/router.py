import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from motor.motor_asyncio import AsyncIOMotorClient

from .servers import TCPServer
from .requester import APISessionMaker
from .registrator import Registrator
from config import API_KEY, DB_URI

router = APIRouter(
    prefix="/register",
    tags=["Registration"]
)


@router.websocket('/ws/create_device')
async def add_new_device(websocket: WebSocket):
    await websocket.accept()
    try:
        process = await asyncio.create_subprocess_shell(
            """source /Users/egor/PycharmProjects/mqtt_homecontrol/hub/venv/bin/activate && 
            python3 /Users/egor/PycharmProjects/mqtt_homecontrol/hub/src/run_broadcast_server.py""",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        requester = APISessionMaker(API_KEY)
        client = AsyncIOMotorClient(DB_URI)
        a = Registrator(requester, client)

        loop = asyncio.get_event_loop()
        server = TCPServer(loop, 12222, a)

        reg_funcs = {}
        async for name, func in server.run_server():
            if name is not None:
                await websocket.send_text(name)
                reg_funcs[name] = func
                print(name)
            try:
                response = await asyncio.wait_for(websocket.receive_text(), 2)
            except TimeoutError:
                continue
            print(response)
            if response is not None:
                result = await reg_funcs[response]()
                print(result)
                if result:
                    await websocket.send_text('success')
                    break
    except WebSocketDisconnect:
        pass
    else:
        await websocket.close()
    finally:
        print('disconnected')
        server.close()
