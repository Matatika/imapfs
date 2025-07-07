"""IMAP filesystem."""

from __future__ import annotations

from fsspec import AbstractFileSystem
from imapclient import IMAPClient
from typing_extensions import override


class IMAPFileSystem(AbstractFileSystem):
    """IMAP filesystem."""

    @override
    def __init__(self, *args, **storage_options) -> None:
        super().__init__(*args, **storage_options)

        host = storage_options.pop("host")
        username = storage_options.pop("username")
        password = storage_options.pop("password")

        self.client = IMAPClient(host)
        self.client.login(username, password)

    @override
    def ls(self, path: str, detail=True, **kwargs):
        if path.endswith("/"):
            path = path[:-1]

        folders = self.client.list_folders(path)

        details = {
            name: {"name": name, "size": 0, "type": "directory"}
            for (*_, name) in folders
        }

        return list(details.values() if detail else details.keys())

    @override
    def __enter__(self) -> None:
        return self

    @override
    def __exit__(self, *args) -> None:
        self.client.logout()
