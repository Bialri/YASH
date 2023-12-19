from aiohttp import ClientSession, BasicAuth
import paho.mqtt.client as mqtt
import asyncio
import json
from datetime import datetime,timedelta
from config import EMQX_PORT, HOST

class MQTTSender:

    def __init__(self, mqtt_user, mqtt_password):
        self.client = mqtt.Client(client_id=mqtt_user)
        self.client.username_pw_set(mqtt_user, mqtt_password)

    async def send_command(self, topic, command):
        self.client.connect(host=HOST,
                            port=EMQX_PORT)

        confirm = None

        def receive_confirm(client, user_data, message):
            print(message.payload)
            nonlocal confirm
            confirm = message.payload.decode()

        self.client.publish(topic=topic,
                            payload=command,
                            qos=2)
        recieve_topic = f'{topic}/publish'
        self.client.subscribe(recieve_topic, qos=0)
        self.client.on_message = receive_confirm
        self.client.loop_start()
        start = datetime.now()

        while not confirm:
            await asyncio.sleep(0.2)
            if datetime.now() - start > timedelta(seconds=20):
                raise TimeoutError("Confirm message hasn't received")
        confirm_dict = json.loads(confirm)

        self.client.loop_stop()
        self.client.disconnect()
        return confirm_dict