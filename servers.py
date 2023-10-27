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
        """Return actual ip address in local network"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # trying to connect to unreachable host
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
    """TCP server that handle devices wanted to connect to hub and prepare registration functions for them"""

    def __init__(self, loop, port, registrator: Registrator):
        self.port = port
        self.stop = False
        self.loop = loop
        self.registrator = registrator

    async def run_server(self):
        """Start server and yield as generator clients wanted to connect"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('', self.port))
        server.listen()
        server.settimeout(50)  # setting timeout to prevent infinite socket.recv wait with no data
        print("Tcp server started")
        while True:
            try:
                conn, addr = await self.loop.sock_accept(server)
            except TimeoutError:
                continue
            print('client addr: ', addr)
            # Process client request, receive client name and prepared registration function
            name, registration_function = await self._handle_client(conn)
            if name is not None:
                yield name, registration_function
            if self.stop:
                break

    @staticmethod
    def _validate_request(json_string, schema):
        """Return validated by received schema object"""
        try:
            device_specification = schema.model_validate_json(json_string)
        except ValidationError as e:
            raise RegistrationError(f'Input string format is not correct. {e}')
        return device_specification

    async def _response(self, client, data):
        """Send response to client"""
        data_encoded = data.encode()
        await self.loop.sock_sendall(client, data_encoded)

    async def _response_error(self, client, error_type, exception):
        """Send error to client"""
        error = ErrorForm(status='failure',
                          type=error_type,
                          detail=str(exception))
        response = error.model_dump_json()
        await self._response(client, response)

    async def rollback(self, device_id):
        """Rollback all data created by registrator"""
        await self.registrator.db_rollback(device_id)
        await self.registrator.emqx_acl_rollback(device_id)
        await self.registrator.emqx_user_rollback(device_id)

    async def _handle_client(self, client):
        """Return clients name and client registration function"""
        input_data = (await self.loop.sock_recv(client, 1024)).decode()
        try:
            device_specification = self._validate_request(input_data, DeviceSpecification)
        # send error and abort client registration function creation
        except RegistrationError as e:
            await self._response_error(client, 'Wrong format', e)
            return None, None

        async def register_client():
            """Return True if device is registered and False if not"""
            try:
                response = await self.registrator.register_device(device_specification)
            except ExceptionGroup:
                await self._response_error(client, 'Registration error', "Internal Error")
                client.close()
                return False

            await self._response(client, json.dumps(response))
            device_id = response['clientid']

            # Trying to receive confirmation from device
            try:
                confirm_data = (await self.loop.sock_recv(client, 1024)).decode()
                confirm_validated = self._validate_request(confirm_data, Confirm)
                if confirm_validated.status:
                    self.stop = True
                # Rollback registration if device send confirmation status False
                else:
                    await self.rollback(device_id)
                    client.close()
                    return False

            # Rollback registration if device send not correct data or doesn't send any data
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
    """UDP server that handle broadcast requests from devices and
    helps them find hub ip address in local network and port"""

    def __init__(self, port, tcp_port):
        self.port = port
        self.tcp_port = tcp_port
        self.event = multiprocessing.Event()

    def stop(self):
        # Set event to stop server
        self.event.set()

    def run_server(self):
        # Start server and handle requests
        self.event.clear()
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        server.bind(('', self.port))
        server.settimeout(5.0)  # Set timeout to prevent infinite sock.recv wait with no data
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
        """Send to client tcp server address and port"""
        recieved_data = client_data[0]
        client_addr = client_data[1]
        print(f'Recieved from: {client_addr[0]}\n data: {recieved_data}')
        return_dict = {'ip': self.get_local_ip(),
                       'port': self.tcp_port}
        time.sleep(1)
        sock.sendto(json.dumps(return_dict).encode(), client_addr)
        print(f'Response sent to server')
