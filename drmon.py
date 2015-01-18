# -*- coding: utf-8 -*-

# カスタマイズはここから

OUTPUT_PATH = "/media/0857-5552"        # 出力先ディレクトリへのパス
SENSOR_PORT = "/dev/ttyACM0"            # センサー出力を受け取るシリアルデバイス
BAUD_RATE = 9600                        # シリアルデバイスのボーレート

# カスタマイズはここまで

import sys, threading, io, signal
import serial                   # for SensorMonitor
import picamera                 # for CameraMonitor
import os, os.path, queue       # for OutputWriter

OUTPUT_FILE = "output.csv"
TIMEOUT_SEC = 10

class SensorMonitor(threading.Thread):
    def __init__(self, sensor_port, baud_rate, camera, writer):
        threading.Thread.__init__(self, name='SensorMonitor')
        self.setDaemon(True)
        self.sensor_port = sensor_port
        self.baud_rate = baud_rate
        self.camera = camera
        self.writer = writer
        self.stop_event = threading.Event()

    def run(self):
        try:
            s = serial.Serial(self.sensor_port, self.baud_rate)
            s.readline() # 最初の行は不完全な可能性があるので読み飛ばす
            while not self.stop_event.is_set() and s.readable():
                l = s.readline()
                val = l.split(",")
                # 加速度に急激な変化があった時はカメラに出力指示
                ts = val[0].join(".h264")
                ax = float(val[4])
                ay = float(val[5])
                az = float(val[6])
                if ax > 0.3 or ay > 0.3:
                    sys.stderr.write("DETECTED RAPID ACCELERATION: {0}, {1}\n".format(ax, ay))
                    self.camera.rec()
                self.writer.write_sensor_value(l)
            sys.stderr.write("FINISHED SENSOR MONITORING\n")
        except serial.SerialException, e:
            sys.stderr.write("SERIAL DEVICE ERROR: {0}\n".format(e))

    def stop(self):
        self.stop_event.set()

# recを呼ぶとその前後20秒の動画を出力する
# http://picamera.readthedocs.org/en/release-1.9/recipes1.html#recording-to-a-circular-stream
class CameraMonitor(threading.Thread):
    def __init__(self, writer):
        threading.Thread.__init__(self, name='CameraMonitor')
        self.setDaemon(True)
        self.writer = writer
        self.name = "dummy.h264"
        self.stop_event = threading.Event()
        self.rec_event = threading.Event()

    def output(self, stream):
        buf = io.BytesIO();
        with stream.lock:
             for frame in stream.frames:
                 if frame.frame_type == picamera.PiVideoFrameType.sps_header:
                     stream.seek(frame.position)
                     break
             buf.write(stream.read())
        return buf

    def run(self):
        with picamera.PiCamera() as camera:
            stream = picamera.PiCameraCircularIO(camera, seconds=20)
            camera.start_recording(stream, format='h264')
            try:
                while not self.stop_event.is_set():
                    camera.wait_recording(1)
                    if self.rec_event.is_set():
                        camera.wait_recording(10)
                        writer.write_video(output(stream), name)
            finally:
                camera.stop_recording()

    def rec(self, name):
        self.name = name
        self.rec_event.set()

    def stop(self):
        self.stop_event.set()

class OutputWriter(threading.Thread):
    def __init__(self, base_path):
        threading.Thread.__init__(self, name='OutputWriter')
        self.base_path = base_path
        self.queue = queue.Queue()
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                op = self.queue.get(timeout=TIMEOUT_SEC)
                try:
                    if op: op()
                except:
                    e = sys.exc_info()
                    sys.stderr.write("WRITING OPERATION ERROR: {0}, {1}\n".format(e[0], e[1]))
                    raise
            except:
                continue

    def write_sensor_value(self, value):
        def op_append():
            p = os.path.join(self.base_path, OUTPUT_FILE)
            with open(p, "a+") as f:  # センサー値を追記
                f.write(str(value))
        self.queue.put(op_append)

    def write_video(self, buf, name):
        def op_write_video():
            p = os.path.join(self.base_path, name)
            buf.seek(0)
            with open(p, "wb") as f:
                f.write(buf.read())
        self.queue.put(op_write_video)

    def stop(self):
        self.stop_event.set()


## ここからメイン処理

if __name__ == "__main__":
    ow = OutputWriter(OUTPUT_PATH)
    cm = CameraMonitor(ow)
    sm = SensorMonitor(SENSOR_PORT, BAUD_RATE, cm, ow)
    def shutdown(signum, sframe):
        sys.stderr.write("CAUGHT SIGNAL ({0})\n".format(signum))
        sys.stderr.write("SHUTTING DOWN NOW... ".format(signum))
        sm.stop()
        cm.stop()
        ow.stop()
        sys.stderr.write("done\n")
        sys.stderr.write("WAITING MODULES... ")
        sm.join()
        cm.join()
        ow.join()
        sys.stderr.write("done\n")
    signal.signal(signal.SIGINT, shutdown)
    ow.start()
    cm.start()
    sm.start()
