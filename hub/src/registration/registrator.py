import secrets
import string
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from .requester import APISessionMaker
from config import HOST, EMQX_PORT
from .exceptions import RegistrationError, RollbackError, RegistrationRequestError
from .schemas import DeviceSpecification



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
        """Create secure password with given length

            Returns:
                str: Password with length set in 'password_len' attribute
        """
        pool = string.ascii_letters + string.digits + string.punctuation
        password = ''.join([secrets.choice(pool) for _ in range(self.password_len)])
        return password

    async def _create_emqx_user(self, client_id: str, password: str):
        """Create EMQX user by api.

            Args:
                client_id(str): Client id.
                password(str): Client password.

            Raises:
                RegistrationRequestError: If create request is not success.
        """
        async with self.session_maker.get_session() as session:
            credentials = {'user_id': client_id,
                           'password': password}
            url = 'http://localhost:18083/api/v5/authentication/password_based:built_in_database/users'
            async with session.post(url=url, json=credentials) as response:
                if str(response.status)[0] != '2':
                    raise RegistrationRequestError("Request error. User is not created")

    async def _insert_object(self, device_object):
        """Insert document of new device

            Args:
                device_object(dict): device json object interpretation.

            Returns:
                 str: ID given to object.
        """
        inserted_id = (await self.db_client.local.devices.insert_one(device_object)).inserted_id
        return str(inserted_id)

    async def emqx_user_rollback(self, device_id):
        """Delete created emqx user.

            Args:
                device_id(str): Device id to delete.

            Raises:
                RollbackError: If response code is not 20X.

        """
        async with self.session_maker.get_session() as session:
            url = f'http://localhost:18083/api/v5/authentication/password_based:built_in_database/users/{device_id}'
            async with session.delete(url=url) as response:
                if str(response.status)[0] != '2':
                    raise RollbackError("Request error. Delete request failed")

    async def emqx_acl_rollback(self, device_id):
        """Delete created acl rules of user.

            Args:
                device_id(str): Device id, rules will be deleted for.

            Raises:
                RollbackError: If response code is not 20X.

        """
        async with self.session_maker.get_session() as session:
            url = f'http://localhost:18083/api/v5/authorization/sources/built_in_database/rules/users/{device_id}'
            async with session.delete(url=url) as response:
                if str(response.status)[0] != '2':
                    raise RollbackError("Request error. Delete request failed")

    async def db_rollback(self, device_id):
        """Delete document of created user.

            Args:
                device_id(str): Document id to delete.

            Raises:
                RollbackError: If document isn't deleted.
        """
        result = await self.db_client.local.devices.delete_one({'_id': ObjectId(device_id)})
        if result.deleted_count == 0:
            raise RollbackError("Id doesn't found")

    async def _set_acl_rules(self, client_id, device_type):
        """Create acl rules for emqx user.

            Args:
                client_id(str): Device id, rules created for.
                device_type(str): Type of device, device or sensor.

            Raises:
                RegistrationError: If response code isn't 20X.
        """
        publish_rule = 'allow' if device_type == 'sensor' else 'deny'
        # If device is sensor, permit to publish data to the topic
        acl_config = [
            {
                'rules': [
                    {'action': 'publish',
                     'permission': publish_rule,
                     'topic': f'/devices/{client_id}/publish'},

                    {'action': 'subscribe',
                     'permission': 'allow',
                     'topic': f'/devices/{client_id}'}
                ],
                'username': client_id
            }
        ]

        async with self.session_maker.get_session() as session:
            url = 'http://localhost:18083/api/v5/authorization/sources/built_in_database/rules/users/'
            async with session.post(url=url, json=acl_config) as response:
                if str(response.status)[0] != '2':
                    raise RegistrationError("Request error. ACL rules is not created")

    async def register_device(self, device_specification: DeviceSpecification):
        """Register device in hub system.

            Args:
                device_specification(DeviceSpecification): Pydantic model with device specification

            Returns:
                dict: Info for device: host and emqx port, credentials, and created topic.

            Raises:
                ExceptionGroup: If device creation aborted on some step.
        """

        device_specification_dict = device_specification.model_dump()

        del device_specification_dict['response_details']

        created_id = await self._insert_object(device_specification_dict)
        device_password = self._create_password()

        try:
            await self._create_emqx_user(created_id, device_password)
        except RegistrationError as e:
            await self.db_rollback(created_id)
            raise ExceptionGroup('User is not created', [e,
                                                         RegistrationError('Request error, creation abort')])

        try:
            await self._set_acl_rules(created_id, device_specification.type)
        except RegistrationError as e:
            await self.db_rollback(created_id)
            await self.emqx_user_rollback(created_id)
            raise ExceptionGroup('User is not created', [e,
                                                         RegistrationError('Request error, creation abort')])

        response = {'host': "111.111.111.111",
                    'port': EMQX_PORT,
                    'clientid': created_id,
                    'password': device_password,
                    'topic': f'/devices/{created_id}'}
        return response
