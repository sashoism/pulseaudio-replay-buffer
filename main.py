import asyncio
import socketio
import toml

sio = socketio.AsyncClient()

@sio.event
def connect():
    print('connected')

async def main():
    config = toml.load('config.toml')
    await sio.connect('http://localhost:3000', auth=config['auth'])
    await asyncio.sleep(1000)


asyncio.run(main())
