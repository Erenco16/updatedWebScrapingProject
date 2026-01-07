import os
import sys
import pickle
import tempfile
from types import SimpleNamespace

# Ensure project root is importable so 'src' package can be imported
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.main as main_module
import src.login as login
import requests
import src.input.send_product_code_mail as spcm


def make_cookies_file(tmp_path):
    data = [{"name": "JSESSIONID", "value": "abc123"}]
    cookie_file = main_module.COOKIE_FILE
    os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
    with open(cookie_file, "wb") as f:
        pickle.dump(data, f)
    return cookie_file


class DummyResponse:
    def __init__(self, status_code=200, headers=None, content=b"content"):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content

    def iter_content(self, chunk_size=8192):
        yield self._content


def test_run_success(monkeypatch, tmp_path):
    # Prepare environment
    os.environ["informal_mail"] = "notify@example.com"

    # Fake driver and elements
    class FakeElement:
        def __init__(self, id_):
            self.id = id_
            self._text = ""
        def click(self):
            self.clicked = True
        def clear(self):
            self.cleared = True
        def send_keys(self, text):
            self._text = text
        def is_displayed(self):
            return True
        def is_enabled(self):
            return True

    class FakeDriver:
        def get(self, url):
            self.url = url
        def find_element(self, by, value):
            return FakeElement(value)
        def execute_script(self, script, element):
            try:
                element.click()
            except Exception:
                pass
        def quit(self):
            pass

    # Dummy wait that immediately resolves using the condition
    class DummyWait:
        def __init__(self, driver, timeout):
            self.driver = driver
        def until(self, condition):
            return condition(self.driver)

    # Mock login.handle_login to return the fake driver
    def fake_handle_login():
        return FakeDriver()

    monkeypatch.setattr(login, "handle_login", fake_handle_login)
    monkeypatch.setattr(spcm, "WebDriverWait", DummyWait)

    # Ensure send_mail is not called on success
    def fake_send_mail(recipient, subject, body):
        raise AssertionError("send_mail should not be called on success")

    monkeypatch.setattr(spcm, "send_mail", fake_send_mail)

    # Run
    spcm.run_send_product_code_mail()

    # If no exception, success path did not call send_mail



def test_download_failure_sends_notification(monkeypatch, tmp_path):
    # Simulate failure during Selenium-driven flow
    monkeypatch.setattr(spcm, "download_datanorm_via_selenium", lambda *args, **kwargs: (_ for _ in ()).throw(Exception("boom")))

    notified = {}

    def fake_send_mail(recipient, subject, body):
        notified["recipient"] = recipient
        notified["subject"] = subject
        notified["body"] = body

    monkeypatch.setattr(spcm, "send_mail", fake_send_mail)

    try:
        spcm.run_send_product_code_mail()
    except Exception:
        pass

    assert "subject" in notified
    assert "Hafele Datanorm Failed" in notified["subject"]
