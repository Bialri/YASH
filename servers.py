import socket
import json
import time
from abc import ABC, abstractmethod
import multiprocessing
from pydantic import ValidationError

from exceptions import RegistrationError
from registrator import Registrator
from schemas import DeviceSpecification, ErrorForm, Confirm


class Server(ABC):

    @abstractmethod
    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            s.connect(('192.255.255.255', 1))
            ip = s.getsockname()[0]
        except:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    @abstractmethod
    async def run_server(self):
        pass

    @abstractmethod
    async def _handle_client(self, *args, **kwargs):
        pass


class TCPServer(Server):

    def __init__(self, loop, port, registrator: Registrator):
        self.port = port
        self.stop = False
        self.loop = loop
        self.registrator = registrator

    async def run_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('', self.port))
        server.listen()
        server.settimeout(50)
        print("Tcp server started")
        while True:
            try:
                conn, addr = await self.loop.sock_accept(server)
            except TimeoutError:
                continue
            print('client addr: ', addr)
            name, registration_function = await self._handle_client(conn)
            # if name is not None:
            yield name, registration_function
            if self.stop:
                break

    @staticmethod
    def _validate_request(json_string, schema):
        try:
            device_specification = schema.model_validate_json(json_string)
        except ValidationError as e:
            raise RegistrationError(f'Input string format is not correct. {e}')
        return device_specification

    async def _response(self, client, data):
        data_encoded = data.encode()
        await self.loop.sock_sendall(client, data_encoded)

    async def _response_error(self, client, error_type, exception):
        error = ErrorForm(status='failure',
                          type=error_type,
                          detail=str(exception))
        response = error.model_dump_json()
        await self._response(client, response)

    async def rollback(self, device_id):
        await self.registrator.db_rollback(device_id)
        await self.registrator.emqx_acl_rollback(device_id)
        await self.registrator.emqx_user_rollback(device_id)

    async def _handle_client(self, client):
        input_data = (await self.loop.sock_recv(client, 1024)).decode()
        try:
            device_specification = self._validate_request(input_data, DeviceSpecification)
        except RegistrationError as e:
            await self._response_error(client, 'Wrong format', e)
            return None, None

        async def register_client():
            try:
                response = await self.registrator.register_device(device_specification)
            except ExceptionGroup:
                await self._response_error(client, 'Registration error', "Internal Error")
                client.close()
                return False

            await self._response(client, json.dumps(response))
            device_id = response['clientid']

            try:
                confirm_data = (await self.loop.sock_recv(client, 1024)).decode()
                confirm_validated = self._validate_request(confirm_data, Confirm)
                if confirm_validated.status:
                    self.stop = True
                else:
                    await self.rollback(device_id)
                    client.close()
                    return False

            except RegistrationError as e:
                await self.rollback(device_id)
                await self._response_error(client, 'Wrong format', e)
                client.close()
                return False

            except TimeoutError:
                await self.rollback(device_id)
                client.close()
                return False
            return True

        return device_specification.name, register_client


class BroadcastServer(Server):

    def __init__(self, port, tcp_port):
        self.port = port
        self.tcp_port = tcp_port
        self.event = multiprocessing.Event()

    def stop(self):
        self.event.set()

    def run_server(self):
        self.event.clear()
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        server.bind(('', self.port))
        server.settimeout(5.0)
        print('udp server started')

        while True:
            if self.event.is_set():
                print("udp server stop")
                break
            try:
                request = server.recvfrom(1024)
            except TimeoutError:
                continue
            except KeyboardInterrupt:
                continue
            print(request[0])
            self._handle_client(server, request)

    def _handle_client(self, sock, client_data):
        recieved_data = client_data[0]
        client_addr = client_data[1]
        print(f'Recieved from: {client_addr[0]}\n data: {recieved_data}')
        return_dict = {'ip': self.get_local_ip(),
                       'port': self.tcp_port}
        time.sleep(1)
        sock.sendto(json.dumps(return_dict).encode(), client_addr)
        print(f'Response sent to server')
