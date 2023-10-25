import socket
import asyncio
import json
from abc import ABC, abstractmethod

from exceptions import RegistrationError, RollbackError
from registrator import Registrator


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
            IP = s.getsockname()[0]
        except:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    @abstractmethod
    async def run_server(self):
        pass

    @abstractmethod
    async def handle_client(self, *args, **kwargs):
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
        print("Started tcp server")
        while True:
            conn, addr = await self.loop.sock_accept(server)

            print('client addr: ', addr)
            await self.handle_client(conn)

            if self.stop:
                print('tcp server stoped')
                break

    async def handle_client(self, client):
        data = await self.loop.sock_recv(client, 1024)
        data_decoded = data.decode()
        try:
            response = self.registrator.register_device(data_decoded)
        except RegistrationError:
            response = {'error: device is not registered'}
        await self.loop.sock_sendall(client, json.dumps(response).encode())
        confirm = await self.loop.sock_recv(client, 1024)
        confirm_decoded = json.loads(confirm.decode())
        if confirm_decoded['staaatus']:
            self.stop = True
        print("message sended")
        client.close()


class BroadcastServer(Server):

    def __init__(self, loop, port, tcp_port):
        self.loop = loop
        self.port = port
        self.tcp_port = tcp_port
        self.stop = False

    async def run_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        server.bind(('', self.port))
        print('udp server started')

        while True:
            request = await self.loop.sock_recvfrom(server, 255)
            print(request[0])
            await self.handle_client(server, request)
            if self.stop:
                print("udp server stoped")
                break

    async def handle_client(self, sock, client_data):
        recieved_data = client_data[0]
        client_addr = client_data[1]
        await asyncio.sleep(1)
        print(f'Recieved from: {client_addr[0]}\n data: {recieved_data}')
        return_dict = {'ip': self.get_local_ip(),
                       'port': self.tcp_port}
        for _ in range(5):
            await asyncio.sleep(0.1)
            await self.loop.sock_sendto(sock, json.dumps(return_dict).encode(), client_addr)
        print(f'Response to server sent')
        self.stop = True