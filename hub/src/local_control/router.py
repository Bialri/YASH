from fastapi import APIRouter, Response, status
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from bson.errors import InvalidId
from config import DB_URI
from schemas import ResponseSchema, ErrorSchema, DeviceResponseSchema

from .schemas import ChangingField, DevicesIdsSchema
from .sender import MQTTSender

sender = MQTTSender("admin", "admin")  # TODO: loading admin credentials

router = APIRouter(
    prefix="/local_control",
    tags=["Local Control"]
)


@router.patch('/devices/{device_id}/change_value/', response_model=ResponseSchema)
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


@router.get('/devices/{device_id}/', response_model=ResponseSchema)
async def get_device(device_id: str,
                     response: Response):
    db_client = AsyncIOMotorClient(DB_URI)
    async with await db_client.start_session() as session:
        async with session.start_transaction():
            collection = session.client.local.devices
            try:
                device = await collection.find_one({'_id': ObjectId(device_id)})
            except InvalidId:
                device = None

            if device is None:
                error = ErrorSchema(type="Invalid id", message="Device not found")
                response_message = ResponseSchema(status="Failure", results=error)
                response.status_code = status.HTTP_400_BAD_REQUEST
                return response_message

            fields_names = [field['name'] for field in device['fields']]
            response_device = DeviceResponseSchema(
                name=device['name'],
                type=device['type'],
                fields=fields_names,
            )
            response = ResponseSchema(status='Success', results=response_device)
            return response


@router.get('/devices/', response_model=ResponseSchema)
async def get_devices(response: Response):
    db_client = AsyncIOMotorClient(DB_URI)
    async with await db_client.start_session() as session:
        async with session.start_transaction():
            collection = session.client.local.devices
            devices = collection.find()
            ids = [str(device['_id']) async for device in devices]
            response_device = DevicesIdsSchema(device_ids=ids)
            response_message = ResponseSchema(status="Success", results=response_device)
            return response_message
