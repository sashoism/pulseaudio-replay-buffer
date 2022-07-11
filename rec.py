import asyncio
from collections import deque
from contextlib import suppress
import signal
import time
import datetime
import pydub
import pulsectl_asyncio as pulsectl

class NoRecordingException(Exception):
    pass


class PulseaudioRecorder:
    def __init__(self, device: str, buffer_seconds=60, bytes_per_sample=2, channels=1, sampling_rate=44100, latency_msec=1000):
        self.recording = False
        self.device = device
        self.parec_args = [
            f'--channels={channels}',
            f'--rate={sampling_rate}',
            f'--latency-msec={latency_msec}']

        bytes_per_second = bytes_per_sample * channels * sampling_rate

        class PulseaudioRecordProtocol(asyncio.SubprocessProtocol):
            buffer = deque(maxlen=bytes_per_second*buffer_seconds)
            last_updated_timestamp = 0.0

            def connection_made(self, transport):
                with suppress(AttributeError):
                    self.on_connection_made()

            def connection_lost(self, exc):
                with suppress(AttributeError):
                    self.on_connection_lost()

            def pipe_data_received(self, fd, data):
                self.last_updated_timestamp = time.time()
                self.buffer.extend(data)

            async def get_recording(self):
                timestamp = time.time()
                while timestamp >= self.last_updated_timestamp:
                    await asyncio.sleep(latency_msec * 0.001)

                truncate_bytes = bytes_per_sample * \
                    int(sampling_rate*channels *
                        (self.last_updated_timestamp - timestamp))

                return \
                    pydub.AudioSegment(
                        bytes(self.buffer)[:-truncate_bytes],
                        sample_width=bytes_per_sample,
                        frame_rate=sampling_rate,
                        channels=1), \
                    datetime.datetime.fromtimestamp(timestamp).isoformat()

        self.protocol_factory = PulseaudioRecordProtocol

    def on_connection_lost(self):
        self.recording = False

    async def start(self):
        self.transport, self.protocol = await asyncio.get_running_loop().subprocess_exec(
            self.protocol_factory,
            'parec', f'--device={self.device}', *self.parec_args)
        self.protocol.on_connection_lost = self.on_connection_lost
        self.recording = True
        print(id(self.protocol), id(self.protocol.buffer))

    async def switch_to(self, device: str):
        self.stop()
        self.device = device
        await self.start()

    def stop(self):
        if self.recording:
            self.transport.kill()
            self.recording = False

    async def get_recording(self):
        if self.recording:
            return await self.protocol.get_recording()
        else:
            raise NoRecordingException


async def main():
    async with pulsectl.PulseAsync() as pulse:
        async def get_default_sink_source():
            server_info = await pulse.server_info()
            return f'{server_info.default_sink_name}.monitor', server_info.default_source_name

        default_sink, default_source = await get_default_sink_source()

        sink_recorder = PulseaudioRecorder(default_sink)
        await sink_recorder.start()

        source_recorder = PulseaudioRecorder(default_source)
        await source_recorder.start()

        async def save_sink_recording():
            audio, timestamp = await sink_recorder.get_recording()
            audio.export(f'sink-recording-{timestamp}.ogg', format='ogg')
        asyncio.get_running_loop().add_signal_handler(
            signal.SIGUSR1, lambda: asyncio.create_task(save_sink_recording()))

        async def save_source_recording():
            audio, timestamp = await source_recorder.get_recording()
            audio.export(f'source-recording-{timestamp}.ogg', format='ogg')
        asyncio.get_running_loop().add_signal_handler(
            signal.SIGUSR2, lambda: asyncio.create_task(save_source_recording()))

        async for event in pulse.subscribe_events('server'):
            new_default_sink, new_default_source = await get_default_sink_source()

            if default_sink != new_default_sink:
                await sink_recorder.switch_to(new_default_sink)
                default_sink = new_default_sink

            if default_source != new_default_source:
                await source_recorder.switch_to(new_default_source)
                default_source = new_default_source

try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass

# TODO: configure params and save location