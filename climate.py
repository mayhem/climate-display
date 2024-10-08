from datetime import datetime
import json
import os
from rgbmatrix import graphics
import socket
import sys
from time import sleep, monotonic
from threading import Thread

from rgbmatrix import RGBMatrix, RGBMatrixOptions
from influxdb import InfluxDBClient
import paho.mqtt.client as mqtt


DATA_UPDATE_INTERVAL = 5
CLIENT_ID = socket.gethostname()

KITCHEN_TEMP_QUERY = """SELECT last("temp")
                          FROM "kitchen"
                         WHERE time >= now() - 2h
                           AND time <= now()
                      GROUP BY time(2m) fill(previous)
                      ORDER BY time DESC"""

KITCHEN_HUM_QUERY = """SELECT last("hum")
                          FROM "kitchen"
                         WHERE time >= now() - 2h
                           AND time <= now()
                      GROUP BY time(2m) fill(previous)
                      ORDER BY time DESC"""

OUTDOOR_TEMP_QUERY = """SELECT last("temp")
                          FROM "balcony"
                         WHERE time >= now() - 2h
                           AND time <= now()
                      GROUP BY time(2m) fill(previous)
                      ORDER BY time DESC"""

OUTDOOR_HUM_QUERY = """SELECT last("hum")
                          FROM "balcony"
                         WHERE time >= now() - 2h
                           AND time <= now()
                      GROUP BY time(2m) fill(previous)
                      ORDER BY time DESC"""

class ClimateDisplay:

    TOPIC = "kitchen-climate-display"

    def __init__(self, *args, **kwargs):

        options = RGBMatrixOptions()
        options.hardware_mapping = "adafruit-hat-pwm"
        options.rows = 32
        options.cols = 64
        options.chain_length = 1
        options.parallel = 1
        options.row_address_type = 0
        options.multiplexing = 0
        options.pwm_bits = 11
        options.brightness = 20
        options.pwm_lsb_nanoseconds = 130
        options.led_rgb_sequence = "RGB"
        options.pixel_mapper_config = ""
        options.panel_type = ""
        options.show_refresh_rate = 0

        options.gpio_slowdown = 1
        options.disable_hardware_pulsing = False
        options.drop_privileges = True

        self.matrix = RGBMatrix(options=options)

        self.canvas = self.matrix.CreateFrameCanvas()
        self.font = graphics.Font()
        self.font.LoadFont("fonts/6x12.bdf")
        self.clear()

        self.client = InfluxDBClient("10.1.1.2", 8086, 'root', 'root', "hippooasis")
        self.outdoor_temp = 0.0
        self.outdoor_hum = 0
        self.kitchen_temp = 0.0
        self.kitchen_hum = 0

        self.mqttc = mqtt.Client(CLIENT_ID)
        self.mqttc.on_message = ClimateDisplay.on_message
        self.mqttc.connect("10.1.1.2", 1883, 60)
        self.mqttc.__self = self
        self.mqttc.subscribe(self.TOPIC)

        self.on = True

 
    @staticmethod
    def on_message(mqttc, user_data, msg):
        try:
            mqttc.__self._handle_message(mqttc, msg)
        except Exception as err:
            traceback.print_exc(file=sys.stdout)

    def _handle_message(self, mqttc, msg):
        payload = str(msg.payload, 'utf-8')
        if msg.topic == self.TOPIC:
            try:
                js = json.loads(str(msg.payload, 'utf-8'))
            except KeyError as err:
                return

            brightness = js.get("brightness", None)
            if brightness is not None and (brightness < 0 or brightness > 100):
                print("bad brightness")
                return

            print("set brightness %d" % brightness)
            if brightness == 0:
                self.on = False
                self.clear()
                self.flip()
            else:
                self.on = True
            self.matrix.brightness = brightness

    def flip(self):
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def print(self, x, y, text, color=(255,255,255)):
        try:
            color = graphics.Color(color[0], color[1], color[2])
            graphics.DrawText(self.canvas, self.font, x, y + (self.font.height - 4), color, text)
        except IndexError:
            pass

    def draw_line(self):
        graphics.DrawLine(self.canvas, 0, 31, 63, 31, graphics.Color(255, 0, 255))

    def clear(self): 
        self.canvas.Clear()

    def query_data(self, query):
        try:
            result = self.client.query(query)
            for value in result.raw["series"][0]["values"]:
                if value[1] is None:
                    continue

                return float(value[1])
                break
        except IndexError:
            return 0.0

        return None

    @staticmethod
    def update_climate_data_callback(cd):
        cd.update_climate_data()

    def update_climate_data(self):
        self.outdoor_temp = self.query_data(OUTDOOR_TEMP_QUERY)
        self.outdoor_hum = int(self.query_data(OUTDOOR_HUM_QUERY))
        self.kitchen_temp = self.query_data(KITCHEN_TEMP_QUERY)
        self.kitchen_hum = int(self.query_data(KITCHEN_HUM_QUERY))

    def update_display(self):

        if not self.on:
            return

        dt = datetime.now()
        self.print(10, 0, "%02d:%02d:%02d" % (dt.hour, dt.minute, dt.second), (255, 80, 0))
        self.print(9, 11, "%02.1fC %02d%%" % (self.kitchen_temp, self.kitchen_hum), (240, 30, 0))
        self.print(2, 11, "i", (240, 30, 0))
        self.print(9, 20, "%02.1fC %02d%%" % (self.outdoor_temp, self.outdoor_hum), (240, 0, 0))
        self.print(2, 20, "o", (240, 0, 0))
        self.draw_line()
        self.flip()

    def run(self):
        self.update_climate_data()
        last_time = int(monotonic())
        next_update = monotonic() + DATA_UPDATE_INTERVAL 
        while True:
            self.update_display()

            if monotonic() >= next_update:
                t = Thread(target=ClimateDisplay.update_climate_data_callback, args=(self,))
                t.start()
                next_update = monotonic() + DATA_UPDATE_INTERVAL

            self.mqttc.loop()
            while last_time == int(monotonic()):
                sleep(.01)

            last_time = int(monotonic())
            self.clear()


if __name__ == "__main__":
    cd = ClimateDisplay()
    cd.run()
