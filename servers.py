import asyncio
from socket import socket, AF_INET, SOCK_DGRAM,  SOCK_STREAM
import json
import time
from abc import ABC, abstractmethod
import multiprocessing
from pydantic import ValidationError
from socket import socket
from asyncio import BaseEventLoop

from exceptions import RegistrationError
from registrator import Registrator
from schemas import DeviceSpecification, ErrorForm, Confirm


class Server(ABC):

    @abstractmethod
    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def get_local_ip():
        """Get actual ip address in local network.

            Returns:
                str: Actual ip address.
        """
        s = socket(AF_INET, SOCK_DGRAM)
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
        """Create new instance of TCP server

            Args:
                loop(BaseEventLoop): Event loop.
                port(int): Port binding to server.
                registrator(Registrator): Registrator instance.
        """
        self.port = port
        self.stop = False
        self.loop = loop
        self.registrator = registrator

        self.server = socket(AF_INET, SOCK_STREAM)
        self.server.bind(('', self.port))

    async def run_server(self):
        """Start server and yield as generator clients wanted to connect

            Yields:
                str: Name of the current client.
                callable: Function for client registration.
        """
        self.server.listen(5)
        self.server.settimeout(10)
        # setting timeout to prevent infinite socket.recv wait with no data
        print("Tcp server started")
        while True:
            try:
                conn, addr = await self.loop.sock_accept(self.server)
            except TimeoutError:
                yield None, None
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
        """Validate json request by given schema.

            Args:
                json_string(str): String requiring validation.
                schema(Model): Pydantic validation schema.

            Returns:
                Model: Validated pydantic model.

            Raises:
                 RegistrationError: If 'json_string' is not correct.
        """
        try:
            device_specification = schema.model_validate_json(json_string)
        except ValidationError as e:
            raise RegistrationError(f'Input string format is not correct. {e}')
        return device_specification

    async def _response(self, client, data):
        """Send response to client.

            Args:
                client(socket): Socket client.
                data(str): Data to send
        """
        data_encoded = data.encode()
        await self.loop.sock_sendall(client, data_encoded)

    def close(self):
        self.server.close()

    async def _response_error(self, client, error_type, exception):
        """Send error to client.

            Args:
                client(socket): Socket client.
                error_type(str): Short traceback of the error.
                exception(Exception): Exception to response
        """
        error = ErrorForm(status='failure',
                          type=error_type,
                          detail=str(exception))
        response = error.model_dump_json()
        await self._response(client, response)

    async def rollback(self, device_id):
        """Rollback all data created by registrator.

            Args:
                device_id(str): ID to delete.
        """
        await self.registrator.db_rollback(device_id)
        await self.registrator.emqx_acl_rollback(device_id)
        await self.registrator.emqx_user_rollback(device_id)

    async def _handle_client(self, client):
        """Return clients name and client registration function

            Args:
                client(socket): Socket client.
            Returns:
                str: Name of the current client.
                callable: Function for client registration.
        """
        try:
            input_data = (await self.loop.sock_recv(client, 1024)).decode()
        except OSError:
            return None, None
        try:
            device_specification = self._validate_request(input_data, DeviceSpecification)
        # send error and abort client registration function creation
        except RegistrationError as e:
            await self._response_error(client, 'Wrong format', e)
            return None, None

        async def register_client():
            """Register device in system

                Returns:
                    bool: True if device is registered or False if not
            """
            client_socket = socket(AF_INET, SOCK_STREAM)
            connection_data = (device_specification.response_details.address, int(device_specification.response_details.port))
            client_socket.connect(connection_data)

            try:
                response = await self.registrator.register_device(device_specification)
            except ExceptionGroup:
                await self._response_error(client_socket, 'Registration error', "Internal Error")
                client_socket.close()
                return False

            await self._response(client_socket, json.dumps(response))
            device_id = response['clientid']

            # Trying to receive confirmation from device
            try:
                confirm_data = (await self.loop.sock_recv(client_socket, 1024)).decode()
                confirm_validated = self._validate_request(confirm_data, Confirm)
                if confirm_validated.status:
                    self.stop = True
                # Rollback registration if device send confirmation status False
                else:
                    await self.rollback(device_id)
                    client_socket.close()
                    return False

            # Rollback registration if device send not correct data or doesn't send any data
            except RegistrationError as e:
                await self.rollback(device_id)
                await self._response_error(client_socket, 'Wrong format', e)
                client_socket.close()
                return False

            except TimeoutError:
                await self.rollback(device_id)
                client_socket.close()
                return False
            return True
        client.close()
        return device_specification.name, register_client


class BroadcastServer(Server):
    """UDP server that handle broadcast requests from devices and
    helps them find hub ip address in local network and port"""

    def __init__(self, port, tcp_port):
        """Create new instance of UDP server.

            Args:
                port(int): Port binding to server.
                tcp_port(int): Port of tcp server.
        """
        self.port = port
        self.tcp_port = tcp_port
        self.event = multiprocessing.Event()

    def stop(self):
        """Set even to stop server."""
        self.event.set()

    def run_server(self):
        """Start UDP server."""
        self.event.clear()
        server = socket(AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
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
        """Send to client tcp server address and port.

            Args:
                sock(socket): UDP socket instance.
                client_data(str): Data received from client.
        """
        received_data = client_data[0]
        client_addr = client_data[1]
        print(f'Received from: {client_addr[0]}\n data: {received_data}')
        return_dict = {'ip': self.get_local_ip(),
                       'port': self.tcp_port}
        time.sleep(1)
        sock.sendto(json.dumps(return_dict).encode(), client_addr)
        print(f'Response sent to server')
