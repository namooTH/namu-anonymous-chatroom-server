from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import json
import asyncio
import random
import string

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RoomsManager:
    def __init__(self):
        self.rooms = {}

    async def create_room(self, name):
        randomnumchar = ''.join(random.choices(string.ascii_uppercase + string.digits, k=9))
        while randomnumchar in self.rooms:
            randomnumchar = ''.join(random.choices(string.ascii_uppercase + string.digits, k=9))
        self.rooms.update({randomnumchar: {"messages": {}, "name": name, "currentmsgid": 0, "activeconnections": [], "respondedconnections": [], "candelete": True, "deletecooldown": 120}})
        return randomnumchar

    async def create_room_forced_code(self, code, name):
        randomnumchar = ''.join(random.choices(string.ascii_uppercase + string.digits, k=9))
        while randomnumchar in self.rooms:
            randomnumchar = ''.join(random.choices(string.ascii_uppercase + string.digits, k=9))
        self.rooms.update({code: {"messages": {}, "name": name, "currentmsgid": 0, "activeconnections": [], "respondedconnections": [], "candelete": False, "deletecooldown": 120}})
        return randomnumchar

    async def connect(self, websocket: WebSocket, room):
        print(self.rooms)
        await websocket.accept()
        self.rooms[room]["activeconnections"].append(websocket)
        self.rooms[room]["respondedconnections"].append(websocket.client.port)
        await self.broadcast(room, f"EVENT_USERJOIN|{len(self.rooms[room]['activeconnections'])}")

    async def disconnect(self, websocket: WebSocket, room):
        self.rooms[room]["activeconnections"].remove(websocket)
        await self.broadcast(room, f"EVENT_USERLEFT|{len(self.rooms[room]['activeconnections'])}")

    async def broadcast(self, room, msg):
        for connection in self.rooms[room]["activeconnections"]:
            await connection.send_text(str(msg))
 
    async def sendmsg(self, room, msg):
        if type(msg) != dict:
            await self.broadcast(msg)
            return
        self.rooms[room]["currentmsgid"] += 1
        self.rooms[room]["messages"].update({self.rooms[room]["currentmsgid"]: msg})
        await self.broadcast(room,json.dumps(({self.rooms[room]["currentmsgid"]: msg})))

    async def deletemsg(self, id, room):
        try:
            self.rooms[room]["messages"].pop(id)
            await self.broadcast(room, f"EVENT_DELETE|{id}")
        except:
            pass

    async def sync(self, websocket: WebSocket, room):
        for i in self.rooms[room]["messages"]:
            await websocket.send_text(json.dumps( {i: self.rooms[room]["messages"][i]} ))
        await websocket.send_text(f'EVENT_NAME|{self.rooms[room]["name"]}')

    # timeout system to check if user has exit the website (without having the connection quited)

    async def updatewsping(self, websocket: WebSocket, room):
        if not websocket.client.port in self.rooms[room]["respondedconnections"]:
            self.rooms[room]["respondedconnections"].append(websocket.client.port)

    async def wsping(self):
        while True:
            for room in self.rooms:
                self.rooms[room]["respondedconnections"].clear()
                await self.broadcast(room, "EVENT_PING")
            await asyncio.sleep(10)
            for room in self.rooms: 
                for connection in self.rooms[room]["activeconnections"]:
                    if not connection.client.port in self.rooms[room]["respondedconnections"]:
                        await self.disconnect(connection, room)

    # delete room if noone using

    async def roomschecker(self):
        while True:
            await asyncio.sleep(1)
            for room in list(self.rooms):
                if self.rooms[room]["deletecooldown"] == 0:
                    self.rooms.pop(room)
                    continue
                if self.rooms[room]["candelete"] and len(self.rooms[room]["activeconnections"]) == 0:
                    self.rooms[room]["deletecooldown"] -= 1
                else:
                    self.rooms[room]["deletecooldown"] = 120

class ConnectionsManager:
    def __init__(self):
        self.chatroomusedip = {}

    async def checkconnection(self, request, type):
        if request.client.host in self.chatroomusedip:
            if type == "createchatroom":
                if self.chatroomusedip[request.client.host]["createchatroom"]["cancreate"]:
                    self.chatroomusedip[request.client.host]["createchatroom"]["time"] = 300
                    self.chatroomusedip[request.client.host]["createchatroom"]["cancreate"] = False
                    return False
                else:
                    if self.chatroomusedip[request.client.host]["createchatroom"]["time"] == 0:
                        self.chatroomusedip[request.client.host]["createchatroom"]["cancreate"] = True
                    else:
                        self.chatroomusedip[request.client.host]["createchatroom"]["time"] -= 1
                        return False
                    return True
            else:
                self.chatroomusedip[request.client.host]["used"] += 1
                if self.chatroomusedip[request.client.host]["used"] > 20:
                    self.chatroomusedip[request.client.host]["cooldown"] = 30 
                if self.chatroomusedip[request.client.host]["cooldown"] > 0:
                    return False
                return True
        else:
            self.chatroomusedip.update({request.client.host: {"used": 0, "cooldown": 0, "createchatroom": {"cancreate": True, "time": 0}}})
            return True

    async def ratelimit(self):
        while True:
            await asyncio.sleep(1)
            for i in self.chatroomusedip:
                if self.chatroomusedip[i]["cooldown"] > 0:
                    self.chatroomusedip[i]["cooldown"] -= 1
                if self.chatroomusedip[i]["used"] > 0:
                    self.chatroomusedip[i]["used"] -= 1

class Item(BaseModel):
    name: str
    message: str | None = None

class ROOMItem(BaseModel):
    name: str

roomsmanager = RoomsManager()
connectionmanager = ConnectionsManager()

@app.on_event("startup")
async def startup_event():
    await roomsmanager.create_room_forced_code("public", "Public")
    await roomsmanager.create_room_forced_code("namuslave", "Namu's Slave Basement")
    asyncio.create_task(connectionmanager.ratelimit())
    asyncio.create_task(roomsmanager.wsping())
    asyncio.create_task(roomsmanager.roomschecker())

@app.websocket("/anonymouschatroom/{room}")
async def websocket_endpoint(websocket: WebSocket, room: str):
    if len(room) > 9:
        return
    await roomsmanager.connect(websocket, room)
    await roomsmanager.sync(websocket, room)
    try:
        while True:
            data = await websocket.receive_text()
            await roomsmanager.updatewsping(websocket, room)
    except WebSocketDisconnect:
        await roomsmanager.disconnect(websocket, room)

@app.api_route('/anonymouschatroom/{room}', methods=['POST', 'OPTIONS'])
async def chatroom(item: Item, request: Request, room: str):
    item = item.dict()
    if not await connectionmanager.checkconnection(request, ""):
        return
    if len(item["message"]) > 2000 or len(item["name"]) > 2000:
        return
    await roomsmanager.sendmsg(room,item)

@app.api_route('/createroom', methods=['POST', 'OPTIONS'])
async def createchatroom(item: ROOMItem, request: Request):
    item = item.dict()
    if not await connectionmanager.checkconnection(request, "createchatroom"):
        return
    return await roomsmanager.create_room(item["name"])