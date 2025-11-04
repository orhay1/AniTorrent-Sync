import httpx

class QBitClient:
    def __init__(self, host, port, username, password, use_https=False):
        protocol = "https" if use_https else "http"
        self.base_url = f"{protocol}://{host}:{port}"
        self.username = username
        self.password = password
        self.client = httpx.Client(follow_redirects=True)
        self.logged_in = False

    def login(self):
        url = f"{self.base_url}/api/v2/auth/login"
        data = {"username": self.username, "password": self.password}
        response = self.client.post(url, data=data)
        if response.text != "Ok.":
            raise Exception("❌ Login to qBittorrent failed.")
        self.logged_in = True

    def add_magnet(self, magnet_link: str, save_path: str = None):
        if not self.logged_in:
            self.login()

        url = f"{self.base_url}/api/v2/torrents/add"
        data = {"urls": magnet_link}
        if save_path:
            data["savepath"] = save_path

        response = self.client.post(url, data=data)
        if response.status_code != 200:
            raise Exception(f"❌ Failed to add magnet: {response.text}")
