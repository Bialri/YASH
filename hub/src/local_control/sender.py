import paho.mqtt.client as mqtt
import asyncio
from datetime import datetime, timedelta
from config import EMQX_PORT, HOST
from .mqtt_schemas import ConfirmSchema, CommandSchema


class MQTTSender:

    def __init__(self, mqtt_user: str, mqtt_password: str) -> None:
        self.client = mqtt.Client(client_id=mqtt_user)
        self.client.username_pw_set(mqtt_user, mqtt_password)
        self.confirm = False
        self.message = None

    def _receive_confirm(self, client, user_data, message):
        confirmation = ConfirmSchema.model_validate_json(message.payload)
        if confirmation.status:
            self.confirm = True
            self.message = confirmation.message

    async def send_command(self, topic: str, command: CommandSchema) -> str:
        self.client.connect(host=HOST,
                            port=EMQX_PORT)

        self.confirm = False
        self.message = None

        self.client.publish(topic=topic,
                            payload=command.model_to_json(),
                            qos=2)
        receive_topic = f'{topic}/publish'
        self.client.subscribe(receive_topic, qos=0)
        self.client.on_message = self._receive_confirm
        self.client.loop_start()
        start = datetime.now()

        while not self.confirm:
            await asyncio.sleep(0.5)
            if datetime.now() - start > timedelta(seconds=20):
                raise TimeoutError("Confirm message hasn't received")

        self.client.loop_stop()
        self.client.disconnect()
        return self.message
