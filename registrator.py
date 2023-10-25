import asyncio
import secrets
import string
import json
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from requester import APISessionMaker
from config import API_KEY, DB_URI, HOST, EMQX_PORT
from exceptions import RegistrationError, RollbackError, RegistrationRequestError


# steps:
# 1. create password
# 2. add user in mongo
# 3. get id and add new user to EMQX
# 4. set acl for user

class Registrator:

    def __init__(self,
                 session_maker: APISessionMaker,
                 db_client: AsyncIOMotorClient,
                 password_len=20):
        self.password_len = password_len
        self.session_maker = session_maker
        self.db_client = db_client

    def _create_password(self):
        pool = string.ascii_letters + string.digits + string.punctuation
        password = ''.join([secrets.choice(pool) for _ in range(self.password_len)])
        return password

    @staticmethod
    def _serialize(string_input):
        dumps_input = json.loads(string_input)
        fields = dumps_input.pop('fields')
        for field in fields:
            dumps_input[field['name']] = eval(field['type'])()
        return dumps_input

    async def _create_emqx_user(self, client_id: str, password: str):
        async with self.session_maker.get_session() as session:
            credentials = {'user_id': client_id,
                           'password': password}
            url = 'http://localhost:18083/api/v5/authentication/password_based:built_in_database/users'
            async with session.post(url=url, json=credentials) as response:
                if str(response.status)[0] != '2':
                    raise RegistrationRequestError("Request error. User is not created")

    async def _insert_object(self, device_object):
        inserted_id = (await self.db_client.local.devices.insert_one(device_object)).inserted_id
        return str(inserted_id)

    async def _emqx_rollback(self, device_id):
        async with self.session_maker.get_session() as session:
            url = f'http://localhost:18083/api/v5/authentication/password_based:built_in_database/users/{device_id}'
            async with session.delete(url=url) as response:
                if str(response.status)[0] != '2':
                    raise RollbackError("Request error. Delete request failed")

    async def _db_rollback(self, device_id):
        result = await self.db_client.local.devices.delete_one({'_id': ObjectId(device_id)})
        if result.deleted_count == 0:
            raise RollbackError("Id doesn't found")

    async def _set_acl_rules(self, client_id, device_type):
        publish_rule = 'allow' if device_type == 'device' else 'deny'

        acl_config = [
            {
                'rules': [
                    {'action': 'publish',
                     'permission': publish_rule,
                     'topic': f'devices/{client_id}'},

                    {'action': 'subscribe',
                     'permission': 'allow',
                     'topic': f'devices/{client_id}'}
                ],
                'username': client_id
            }
        ]

        async with self.session_maker.get_session() as session:
            url = 'http://localhost:18083/api/v5/authorization/sources/built_in_database/rules/users/'
            async with session.post(url=url, json=acl_config) as response:
                if str(response.status)[0] != '2':
                    raise RegistrationError("Request error. ACL rules is not created")

    async def register_device(self, income_str):
        fields = self._serialize(income_str)
        created_id = await self._insert_object(fields)
        device_password = self._create_password()

        try:
            await self._create_emqx_user(created_id, device_password)
        except RegistrationError as e:
            await self._db_rollback(created_id)
            raise ExceptionGroup('User is not created', [e,
                                                         RegistrationError('Request error, creation abort')])

        try:
            await self._set_acl_rules(created_id, fields['type'])
        except RegistrationError as e:
            await self._db_rollback(created_id)
            await self._emqx_rollback(created_id)
            raise ExceptionGroup('User is not created', [e,
                                                         RegistrationError('Request error, creation abort')])

        response = {'host': HOST,
                    'port': EMQX_PORT,
                    'clientid': created_id,
                    'password': device_password,
                    'topic': f'/devices/{created_id}'}
        return response
