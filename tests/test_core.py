"""IMAP filesystem tests."""

import os
import uuid
import warnings
from datetime import datetime, timezone
from email.message import EmailMessage
from smtplib import SMTP

import pytest
from dotenv import load_dotenv
from imapclient import IMAPClient
from imapfs.core import IMAPFileSystem

TEST_FOLDER_NAME = f"imapfs-{uuid.uuid4()}"
TEST_SUBFOLDER_NAME = f"{TEST_FOLDER_NAME}/subfolder"

TEST_FOLDER = {"name": TEST_FOLDER_NAME, "size": 0, "type": "directory"}
TEST_SUBFOLDER = {"name": TEST_SUBFOLDER_NAME, "size": 0, "type": "directory"}

INBOX_NAME = "INBOX"
INBOX_FOLDER = {"name": INBOX_NAME, "size": 0, "type": "directory"}


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


@pytest.fixture(scope="session")
def smtp_client():
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    with SMTP(host, 587) as client:
        client.starttls()
        client.login(username, password)
        yield client


@pytest.fixture(scope="session")
def test_message_search_criteria(smtp_client: SMTP):
    return [
        "FROM",
        smtp_client.user,
        "TO",
        os.getenv("IMAP_USERNAME"),
        "SINCE",
        datetime.now(tz=timezone.utc).date(),
    ]


@pytest.fixture(scope="session", autouse=True)
def create_test_folders(imap_client: IMAPClient):
    imap_client.create_folder(TEST_FOLDER_NAME)
    imap_client.create_folder(TEST_SUBFOLDER_NAME)


@pytest.fixture(scope="session", autouse=True)
def send_message(smtp_client: SMTP):
    msg = EmailMessage()
    msg["Subject"] = "imapfs test email"
    msg["From"] = smtp_client.user
    msg["To"] = os.getenv("IMAP_USERNAME")
    msg.set_content(TEST_FOLDER_NAME)

    smtp_client.send_message(msg)


@pytest.fixture(scope="session", autouse=True)
def delete_test_messages(imap_client: IMAPClient, test_message_search_criteria):
    yield

    folders = imap_client.list_folders()
    trash_flagged = [name for (flags, _, name) in folders if b"\\Trash" in flags]

    imap_client.select_folder(INBOX_NAME)

    if (num_trash := len(trash_flagged)) == 1:
        trash = trash_flagged[0]

        msg_ids = imap_client.search(test_message_search_criteria)
        imap_client.move(msg_ids, trash)

        imap_client.select_folder(trash)
    else:
        warnings.warn(
            f"Found {num_trash} folders with the `Trash` flag, so will not move any "
            "test messages; attempting expunge regardless",
            stacklevel=1,
        )

    msg_ids = imap_client.search(test_message_search_criteria)

    imap_client.delete_messages(msg_ids)
    imap_client.uid_expunge(msg_ids)

    imap_client.delete_folder(TEST_FOLDER_NAME)
    imap_client.delete_folder(TEST_SUBFOLDER_NAME)


@pytest.fixture
def move_to_test_folder(imap_client: IMAPClient, test_message_search_criteria):
    imap_client.select_folder(INBOX_NAME)
    inbox_msg_id = imap_client.search(test_message_search_criteria)[0]
    imap_client.move(inbox_msg_id, TEST_FOLDER_NAME)

    imap_client.select_folder(TEST_FOLDER_NAME)
    folder_msg_id = imap_client.search(test_message_search_criteria)[0]

    yield folder_msg_id

    imap_client.select_folder(TEST_FOLDER_NAME)
    imap_client.move(folder_msg_id, INBOX_NAME)


@pytest.fixture
def move_to_test_subfolder(imap_client: IMAPClient, test_message_search_criteria):
    imap_client.select_folder(INBOX_NAME)
    inbox_msg_id = imap_client.search(test_message_search_criteria)[0]
    imap_client.move(inbox_msg_id, TEST_SUBFOLDER_NAME)

    imap_client.select_folder(TEST_SUBFOLDER_NAME)
    subfolder_msg_id = imap_client.search(test_message_search_criteria)[0]

    yield subfolder_msg_id

    imap_client.select_folder(TEST_SUBFOLDER_NAME)
    imap_client.move(subfolder_msg_id, INBOX_NAME)


@pytest.mark.parametrize("path", ["", "/"], ids=["empty string", "single slash"])
def test_ls_root(fs: IMAPFileSystem, path):
    objects = fs.ls(path)
    assert INBOX_FOLDER in objects
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
def test_ls_folder(fs: IMAPFileSystem, move_to_test_folder, path):
    objects = fs.ls(path)
    assert objects == [
        TEST_FOLDER,
        TEST_SUBFOLDER,
        {
            "name": move_to_test_folder,
            "size": 0,
            "type": "directory",
        },
    ]


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
def test_ls_folder_no_detail(fs: IMAPFileSystem, move_to_test_folder, path):
    objects = fs.ls(path, detail=False)
    assert objects == [TEST_FOLDER_NAME, TEST_SUBFOLDER_NAME, move_to_test_folder]


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
def test_ls_subfolder(fs: IMAPFileSystem, move_to_test_subfolder, path):
    objects = fs.ls(path)
    assert objects == [
        TEST_SUBFOLDER,
        {
            "name": move_to_test_subfolder,
            "size": 0,
            "type": "directory",
        },
    ]
