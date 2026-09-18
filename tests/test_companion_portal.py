"""Portal pairing and same-origin guards without device or microphone IO."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.access import Access, preferred_address
from apps.companion.config import validate
from apps.companion.diagnostics import Diagnostics
from apps.companion.server import Server

class Core:
    def __init__(self, filename):
        self.config={"lan_access":True,"pairing_file":filename}
        self.diagnostics=Diagnostics(system_reader=lambda:("",True))
        self.actions=[]
    def snapshot(self):return {"muted":True,"control_mode":"device"}
    def action(self, value):self.actions.append(value);return self.snapshot()

class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.core=Core(str(Path(self.temp.name)/"code"))
        self.server=Server(("127.0.0.1",0),self.core)
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,method="GET",body=None,headers=None):
        c=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=2)
        h={"Content-Type":"application/json"};h.update(headers or {})
        c.request(method,path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
    def test_local_access_and_code_never_in_url(self):
        status,_,data=self.request("/api/access")
        value=json.loads(data);self.assertEqual(status,200)
        self.assertEqual(value["pairing_code"],self.server.access.code)
        self.assertNotIn(self.server.access.code,value["device_url"])
        self.assertEqual(Path(self.core.config["pairing_file"]).stat().st_mode & 0o777,0o600)
    def test_lan_requires_pairing_then_cookie(self):
        with patch.object(Access,"local",return_value=False):
            self.assertEqual(self.request("/api/status")[0],401)
            self.assertEqual(self.request("/vision/stream")[0],401)
            value=json.loads(self.request("/api/access")[2]);self.assertNotIn("pairing_code",value)
            status,h,_=self.request("/api/pair","POST",{"code":self.server.access.code})
            self.assertEqual(status,200);cookie=h["Set-Cookie"]
            self.assertIn("HttpOnly",cookie);self.assertIn("SameSite=Strict",cookie)
            self.assertEqual(self.request("/api/status",headers={"Cookie":cookie})[0],200)
    def test_nonascii_code_is_bad_request(self):
        self.assertEqual(self.request("/api/pair","POST",{"code":"中文"})[0],400)

    def test_cross_origin_and_foreign_host_rejected(self):
        self.assertEqual(self.request("/api/action","POST",{"action":"unmute"},{"Origin":"http://evil.test"})[0],403)
        self.assertEqual(self.request("/api/access",headers={"Host":"evil.test:1234"})[0],403)
        self.assertEqual(self.core.actions,[])
    def test_pair_rate_limit_and_wrong_cookie(self):
        a=self.server.access
        for _ in range(5):
            with self.assertRaises(ValueError):a.pair("99999999" if a.code != "99999999" else "88888888")
        with self.assertRaises(ValueError):a.pair(a.code)
        self.assertFalse(a.authorized("192.168.1.3","rtctrl_session=bogus"))
    def test_filtered_log_export_and_invalid_filter(self):
        self.core.diagnostics.emit("continuous_started")
        self.assertEqual(len(json.loads(self.request("/api/logs")[2])["entries"]),1)
        self.assertEqual(self.request("/api/logs?source=../../etc/passwd")[0],400)
        status,h,data=self.request("/api/logs/export?source=app&level=error")
        self.assertEqual(status,200);self.assertIn("attachment",h["Content-Disposition"])
        self.assertEqual(json.loads(data)["entries"],[])
    def test_phone_qr_prefers_wifi_even_from_wired_page(self):
        interfaces = [{"address":"192.168.50.2","kind":"wired"},
                      {"address":"192.168.102.211","kind":"wifi"}]
        self.assertEqual(preferred_address(interfaces,"192.168.50.2"),"192.168.102.211")
        self.assertEqual(preferred_address(interfaces[:1],"127.0.0.1"),"192.168.50.2")
        self.assertEqual(preferred_address([],"127.0.0.1"),"127.0.0.1")

    def test_config_explicit_lan_optin(self):
        with self.assertRaises(ValueError):validate({"bind":"0.0.0.0"})
        self.assertTrue(validate({"bind":"0.0.0.0","lan_access":True,"standalone_voice":True})["standalone_voice"])
        with self.assertRaises(ValueError):validate({"vision_url":"http://example.com"})

if __name__=="__main__":unittest.main()
