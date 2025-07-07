"""IMAP filesystem tests."""

import os
import uuid

import pytest
from dotenv import load_dotenv
from imapclient import IMAPClient
from imapfs.core import IMAPFileSystem

TEST_FOLDER_NAME = f"imapfs-{uuid.uuid4()}"
TEST_SUBFOLDER_NAME = f"{TEST_FOLDER_NAME}/subfolder"

TEST_FOLDER = {"name": TEST_FOLDER_NAME, "size": 0, "type": "directory"}
TEST_SUBFOLDER = {"name": TEST_SUBFOLDER_NAME, "size": 0, "type": "directory"}
INBOX = {"name": "INBOX", "size": 0, "type": "directory"}


load_dotenv()


@pytest.fixture(scope="session")
def fs():
    with IMAPFileSystem(
        host=os.getenv("IMAP_HOST"),
        username=os.getenv("IMAP_USERNAME"),
        password=os.getenv("IMAP_PASSWORD"),
    ) as fs:
        yield fs


@pytest.fixture(scope="session")
def imap_client(fs: IMAPFileSystem):
    return fs.client


@pytest.fixture(scope="session", autouse=True)
def setup(imap_client: IMAPClient):
    imap_client.create_folder(TEST_FOLDER_NAME)
    imap_client.create_folder(TEST_SUBFOLDER_NAME)


@pytest.fixture(scope="session", autouse=True)
def teardown(imap_client: IMAPClient):
    yield
    imap_client.delete_folder(TEST_FOLDER_NAME)
    imap_client.delete_folder(TEST_SUBFOLDER_NAME)


@pytest.mark.parametrize("path", ["", "/"], ids=["empty string", "single slash"])
def test_ls_root(fs: IMAPFileSystem, path):
    objects = fs.ls(path)
    assert INBOX in objects
    assert TEST_FOLDER in objects


@pytest.mark.parametrize(
    "path",
    [
        TEST_FOLDER_NAME,
        f"/{TEST_FOLDER_NAME}",
        f"{TEST_FOLDER_NAME}/",
        f"/{TEST_FOLDER_NAME}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_folder(fs: IMAPFileSystem, path):
    objects = fs.ls(path)
    assert objects == [TEST_FOLDER, TEST_SUBFOLDER]


@pytest.mark.parametrize(
    "path",
    [
        TEST_FOLDER_NAME,
        f"/{TEST_FOLDER_NAME}",
        f"{TEST_FOLDER_NAME}/",
        f"/{TEST_FOLDER_NAME}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_folder_no_detail(fs: IMAPFileSystem, path):
    objects = fs.ls(path, detail=False)
    assert objects == [TEST_FOLDER_NAME, TEST_SUBFOLDER_NAME]


@pytest.mark.parametrize(
    "path",
    [
        TEST_SUBFOLDER_NAME,
        f"/{TEST_SUBFOLDER_NAME}",
        f"{TEST_SUBFOLDER_NAME}/",
        f"/{TEST_SUBFOLDER_NAME}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_subfolder(fs: IMAPFileSystem, path):
    objects = fs.ls(path)
    assert objects == [TEST_SUBFOLDER]
