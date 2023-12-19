from fastapi import APIRouter, Response, status
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from config import DB_URI
from schemas import ResponseSchema, ErrorSchema

from .schemas import ChangingField
from .sender import MQTTSender

sender = MQTTSender("admin", "admin")  # TODO: loading admin credentials

router = APIRouter(
    prefix="/local_control",
    tags=["Local Control"]
)


@router.post('/change_value/{device_id}/')
async def chage_value(device_id: str,
                      changing_fields: list[ChangingField],
                      response: Response):
    db_client = AsyncIOMotorClient(DB_URI)
    async with await db_client.start_session() as session:
        async with session.start_transaction():
            collection = session.client.local.devices
            id_filter = {"_id": ObjectId(device_id)}
            device = await collection.find_one(id_filter)
            fields = device['fields']
            for field_to_change in changing_fields:
                for field in fields:
                    if field_to_change.name == field['name']:
                        if field['type'] in ['int', 'float']:
                            if field_to_change.value not in range(field['min'], field['max'] + 1):
                                response.status = status.HTTP_400_BAD_REQUEST
                                error = ErrorSchema(type='Invalid value',
                                                    message=f'Value must be between {field["min"]} and {field["max"]}')
                                response_message = ResponseSchema(status="Failure", results=error)
                                return response_message


                        topic = f'/devices/{str(device["_id"])}'
                        # TODO: exception handler
                        await sender.send_command(topic, field_to_change.model_dump_json())
                        await collection.update_one(id_filter,
                                                    {'$set': {f"fields.$[fields].value": field_to_change.value}},
                                                    array_filters=[{'fields.name': field_to_change.name}])
                        break

                else:
                    error = ErrorSchema(type='Invalid Field', message=f'{device_id} has not "{field_to_change}" field')
                    response_message = ResponseSchema(status="Failure", results=error)
                    return response_message
            changed_device = await collection.find_one(id_filter)
            await session.commit_transaction()
            changed_device["_id"] = str(changed_device["_id"])
            return ResponseSchema(status='Success',
                                  results=changed_device)
