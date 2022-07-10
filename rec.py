import asyncio
from collections import deque
import signal
import time
import datetime
import pydub
import pulsectl_asyncio as pulsectl


async def pulseaudio_listen():
    # TODO: reconnect on error (e.g. PulseDisconnect)
    async with pulsectl.PulseAsync() as pulse:
        async for event in pulse.subscribe_events('server'):
            server_info = await pulse.server_info()
            print(server_info.default_sink_name,
                  server_info.default_source_name)
            # TODO: when the default sink or source changes,
            # switch recording the new one while piping to the same buffer
            # TODO: investigate latency overhead of switching


async def main():
    # TODO: [argparse] configure buffer_seconds and sampling settings
    # TODO: add option to export both audio tracks (default source and sink) merged

    bytes_per_sample = 2  # parecord default is s16ne (16-bit)
    channels = 1
    sampling_rate = 44100

    bytes_per_second = bytes_per_sample * channels * sampling_rate

    buffer_seconds = 60
    buffer = deque(maxlen=bytes_per_second*buffer_seconds)

    buffer_request_timestamp = None

    # TODO: extract signaling and add option for socket.io client
    def signal_handler(signum, frame):
        nonlocal buffer_request_timestamp
        buffer_request_timestamp = time.time()
    signal.signal(signal.SIGUSR1, signal_handler)

    class PulseaudioRecordProtocol(asyncio.SubprocessProtocol):
        def pipe_data_received(self, fd, data):
            last_updated_timestamp = time.time()
            buffer.extend(data)

            nonlocal buffer_request_timestamp
            if buffer_request_timestamp:
                truncate_bytes = bytes_per_sample * \
                    int(sampling_rate*channels *
                        (last_updated_timestamp - buffer_request_timestamp))
                pydub.AudioSegment(
                    bytes(buffer)[:-truncate_bytes],
                    sample_width=bytes_per_sample,
                    frame_rate=sampling_rate,
                    channels=1,
                ).export(f'recording-{datetime.datetime.fromtimestamp(buffer_request_timestamp).isoformat()}.wav', format='wav')
                buffer_request_timestamp = None

    # TODO: adapt for target device changes, run two concurrently (make nonlocal vars fields of protocol impl.)
    await loop.subprocess_exec(
        PulseaudioRecordProtocol,
        'parecord',
        '--device=@DEFAULT_SINK@.monitor',
        f'--channels={channels}',
        f'--rate={sampling_rate}',
        '--latency-msec=1000',
        '--raw',
    )

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
loop.run_until_complete(pulseaudio_listen())
loop.run_forever()
# TODO: graceful shutdown, idiomatic coroutine launching