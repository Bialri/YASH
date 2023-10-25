from aiohttp import ClientSession, BasicAuth


class APISessionMaker:

    def __init__(self, api_key: str):
        username, password = api_key.split(':')
        self.auth_header = BasicAuth(username, password)

    def get_session(self):
        return ClientSession(auth=self.auth_header)