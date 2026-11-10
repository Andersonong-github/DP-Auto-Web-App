import requests
import ssl
import urllib3
from requests.adapters import HTTPAdapter
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _build_ssl_context():
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("ALL:@SECLEVEL=0")
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        return ctx
    except Exception:
        return None


class _InsecureAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = _build_ssl_context()
        if ctx is not None:
            kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _mount_session(session, insecure=True):
    try:
        session.mount("https://", _InsecureAdapter() if insecure else HTTPAdapter())
    except Exception:
        pass
    return session


class RestClient:
    @staticmethod
    def _is_private_ip(host):
        parts = host.split('.')
        if len(parts) != 4:
            return False
        if not all(p.isdigit() for p in parts):
            return False
        first, second = int(parts[0]), int(parts[1])
        return (first == 10 or first == 127 or
                (first == 172 and 16 <= second <= 31) or
                (first == 192 and second == 168))

    def __init__(self, base_url, verify=False):
        base_url = base_url.strip()
        if not base_url.startswith("http://") and not base_url.startswith("https://"):
            host = base_url.split('/')[0].split(':')[0]
            if self._is_private_ip(host):
                base_url = "http://" + base_url
            else:
                base_url = "https://" + base_url
        self.base_url = base_url.rstrip('/')
        self.authenticated = False
        self.last_error = ""
        self.login_mode = "restful"
        self.verify = verify

    @property
    def has_session(self):
        return self.authenticated

    def login(self, username, password):
        self.last_error = ""
        self.authenticated = False
        self.session = _mount_session(requests.Session(), insecure=not self.verify)
        ok = self._login_via_restful(username, password)
        if not ok and self.base_url.startswith("http://"):
            # Server redirects http -> https, which loses the POST body.
            # Retry automatically over https.
            self.base_url = "https://" + self.base_url[len("http://"):]
            self.last_error = ""
            self.authenticated = False
            self.session = _mount_session(requests.Session(), insecure=not self.verify)
            self.log_http_upgrade = True
            ok = self._login_via_restful(username, password)
        return ok

    def _login_via_restful(self, username, password):
        url = f"{self.base_url}/RESTful/index.php/auth/login"
        payload = {
            "lang": "en",
            "userId": username,
            "password": password,
            "response": "json"
        }
        try:
            resp = self.session.post(url, data=payload, timeout=30, verify=self.verify)
            try:
                data = resp.json()
            except Exception:
                # Not JSON -> RESTful login endpoint may not exist on this server.
                return self._login_via_auth_process(username, password,
                                                   reason=f"RESTful auth/login not available ({resp.status_code})")

            if data.get("success"):
                self.authenticated = True
                return True
            else:
                # Success flag false: could be wrong credentials OR endpoint mismatch.
                # Fall back to web-session login to also cover the latter.
                return self._login_via_auth_process(username, password,
                                                   reason=f"RESTful auth/login rejected ({data})")

        except requests.exceptions.SSLError as e:
            self.last_error = f"SSL Error: {e}"
            return False
        except requests.exceptions.ConnectionError as e:
            self.last_error = f"Connection Error: {e}"
            return False
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    def _login_via_auth_process(self, username, password, reason=""):
        """Web-session login for UC servers without a RESTful auth/login controller."""
        try:
            # Establish a session first, like the browser does (sets PHPSESSID cookie).
            try:
                self.session.get(f"{self.base_url}/", timeout=30, verify=self.verify, allow_redirects=True)
            except Exception:
                pass
            self.session.cookies.set("DELTAPATH_COOKIE_POLICY", "v1")

            auth_url = f"{self.base_url}/modules/auth/authProcess.php"
            resp = self.session.post(auth_url, data={
                "userId": username,
                "password": password,
                "action": "login",
                "response": "json",
                "lang": "en",
            }, timeout=30, verify=self.verify, allow_redirects=True)
            text = resp.text or ""
            try:
                data = resp.json()
            except Exception:
                data = None

            if data is not None and data.get("success") is False:
                self.last_error = f"Login failed. Response: {data}"
                return False

            # authProcess returned JSON success OR the session was established.
            # Verify the session actually works against a RESTful controller:
            # a JSON response (not the login page) means the session is authenticated.
            if self._session_can_access_rest():
                self.authenticated = True
                self.login_mode = "session"
                self.last_error = ""
                return True

            self.last_error = (f"Login failed via authProcess.php. {reason} "
                               f"Response: {text[:300]}")
            return False

        except requests.exceptions.SSLError as e:
            self.last_error = f"SSL Error (authProcess): {e}"
            return False
        except requests.exceptions.ConnectionError as e:
            self.last_error = f"Connection Error (authProcess): {e}"
            return False
        except Exception as e:
            self.last_error = f"{type(e).__name__} (authProcess): {e}"
            return False
        return self.authenticated

    def _session_can_access_rest(self):
        """Probe a RESTful controller with the current session; return True if it
        responds with JSON (authenticated) instead of the HTML login page."""
        probes = [
            "RESTful/index.php/get/configuration/aclgroup/view/list",
            "RESTful/index.php/v1/get/user/userprofile/view/list",
            "RESTful/index.php/v2/get/customer/customer/view/list",
        ]
        for endpoint in probes:
            try:
                resp = self.session.get(
                    f"{self.base_url}/{endpoint}",
                    params={"start": 0, "limit": 1},
                    timeout=20, verify=self.verify, allow_redirects=True)
                if resp.status_code == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "json" in ct.lower():
                        return True
                    try:
                        resp.json()
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def get(self, endpoint, params=None):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=params, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"GET error: {e}"
            raise

    def get_customer_by_name(self, eng_name):
        try:
            resp = self.get("RESTful/index.php/v2/get/customer/customer/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"List API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            for row in rows:
                if row.get("engName") == eng_name:
                    return row
            self.last_error = f"No customer found with engName='{eng_name}'"
            return None
        except Exception as e:
            self.last_error = f"get_customer error: {e}"
            return None

    def get_customer_code_by_name(self, eng_name):
        row = self.get_customer_by_name(eng_name)
        if row:
            return row.get("code") or row.get("customerCode") or row.get("id") or ""
        return ""

    def get_customer_id_by_name(self, eng_name):
        row = self.get_customer_by_name(eng_name)
        if row:
            return row.get("customerId") or row.get("id")
        return None

    def search_customer_ids_by_name(self, name_prefix):
        try:
            resp = self.get("RESTful/index.php/v2/get/customer/customer/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"List API HTTP {resp.status_code}"
                return []
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            p = name_prefix.lower()
            for row in rows:
                en = row.get("engName", "") or ""
                if en.lower().startswith(p):
                    cid = str(row.get("customerId") or row.get("id") or "")
                    if cid:
                        results.append(cid)
            return results
        except Exception as e:
            self.last_error = f"search_customer_ids error: {e}"
            return []

    def get_group_name_by_id(self, customer_id):
        try:
            resp = self.get("RESTful/index.php/v2/get/customer/customer/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"List API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            cid = str(customer_id)
            for row in rows:
                rid = str(row.get("customerId") or row.get("id") or "")
                if rid == cid:
                    return row.get("engName") or row.get("name") or ""
            self.last_error = f"No customer found with id='{cid}'"
            return None
        except Exception as e:
            self.last_error = f"get_group_name error: {e}"
            return None

    def _extract_group(self, row):
        for key in ("group", "customerId", "customer_id", "customerID", "cid", "groupId", "group_id"):
            val = row.get(key)
            if val is not None and val != "":
                return str(val)
        return ""

    def search_contexts_by_prefix(self, prefix):
        self.last_error = ""
        try:
            resp = self.get("RESTful/index.php/v1/get/numberingplan/context/view/list",
                            {"start": 0, "limit": 1000})
            if resp.status_code != 200:
                self.last_error = f"Context list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            prefix_lower = prefix.lower()
            for row in rows:
                ctx_id = row.get("contextID") or row.get("name") or ""
                if prefix_lower and not ctx_id.lower().startswith(prefix_lower):
                    continue
                gname = row.get("group") or row.get("groupName") or ""
                results.append({
                    "id": row.get("id") or row.get("ID"),
                    "contextID": ctx_id,
                    "groupName": str(gname),
                })
            return results
        except Exception as e:
            self.last_error = f"search_contexts error: {e}"
            return None

    def search_contexts_by_group(self, customer_id, group_name=""):
        self.last_error = ""
        try:
            resp = self.get("RESTful/index.php/v1/get/numberingplan/context/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"Context list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            cid = str(customer_id or "")
            for row in rows:
                ctx_id = row.get("contextID") or row.get("name") or ""
                if not ctx_id:
                    continue
                gname = str(row.get("group") or row.get("groupName") or "")
                if cid and (gname == cid or str(row.get("customerId") or "") == cid):
                    results.append({"contextID": ctx_id, "groupName": gname})
                elif group_name and gname == group_name:
                    results.append({"contextID": ctx_id, "groupName": gname})
            return results
        except Exception as e:
            self.last_error = f"search_contexts_by_group error: {e}"
            return None

    def get_context_detail(self, context_id):
        self.last_error = ""
        try:
            resp = self.get(f"RESTful/index.php/v1/get/numberingplan/context/{context_id}")
            if resp.status_code == 200:
                data = resp.json()
                d = data.get("data") or {}
                if d:
                    return {
                        "id": d.get("id") or d.get("ID"),
                        "contextID": d.get("contextID") or "",
                        "group": str(d.get("group", "") or ""),
                        "groupName": str(d.get("groupName", "") or ""),
                    }
            return None
        except Exception as e:
            self.last_error = f"get_context_detail error: {e}"
            return None

    def search_permgroups_by_prefix(self, prefix):
        self.last_error = ""
        try:
            resp = self.get("RESTful/index.php/v1/get/numberingplan/permissiongroup/view/list",
                            {"start": 0, "limit": 1000})
            if resp.status_code != 200:
                self.last_error = f"PermGroup list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            prefix_lower = prefix.lower()
            for row in rows:
                title = row.get("contextTitle") or row.get("title") or row.get("name") or ""
                if prefix_lower and not title.lower().startswith(prefix_lower):
                    continue
                gname = row.get("group") or row.get("groupName") or ""
                results.append({
                    "id": row.get("id") or row.get("ID"),
                    "contextTitle": title,
                    "groupName": str(gname),
                })
            return results
        except Exception as e:
            self.last_error = f"search_permgroups error: {e}"
            return None

    def get_permgroup_detail(self, title):
        self.last_error = ""
        try:
            resp = self.get(f"RESTful/index.php/v1/get/numberingplan/permissiongroup/{title}")
            if resp.status_code == 200:
                data = resp.json()
                d = data.get("data") or {}
                if d:
                    return {
                        "id": d.get("id") or d.get("ID"),
                        "contextTitle": d.get("contextTitle") or "",
                        "group": str(d.get("group", "") or ""),
                    }
            return None
        except Exception as e:
            self.last_error = f"get_permgroup_detail error: {e}"
            return None

    def search_outboundroutings_by_sippeer(self, sippeer_value, customer_id="", group_name="", code="", peer_ids=None):
        try:
            resp = self.get("RESTful/index.php/v1/get/numberingplan/outboundrouting/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"OutboundRouting list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            if rows:
                self._debug_fields = list(rows[0].keys())
                self._debug_sample = rows[0]
            results = []
            cid = str(customer_id or "").lower()
            code_lower = (code or "").lower()
            gname = (group_name or sippeer_value or "").lower()
            peer_ids_lower = set(p.lower() for p in (peer_ids or []) if p)
            for row in rows:
                peer = (row.get("peerID") or row.get("sippeer") or row.get("sippeer_value")
                        or row.get("sippeerValue") or row.get("peer_display") or row.get("name") or "")
                peer_lower = peer.lower()
                matched = (peer_lower == code_lower or peer_lower == cid or peer_lower == gname)
                if not matched and peer_ids_lower:
                    matched = peer_lower in peer_ids_lower
                if not matched:
                    continue
                results.append({
                    "routing_id": row.get("routing_id") or row.get("routingId") or row.get("id") or row.get("ID"),
                    "number": row.get("number", ""),
                    "sippeer_value": peer,
                })
            return results
        except Exception as e:
            self.last_error = f"search_outboundroutings error: {e}"
            return None

    def search_calleridmanipulations_by_peer(self, peer_value, customer_id="", group_name="", code="", peer_ids=None):
        try:
            resp = self.get("RESTful/index.php/numberingplan/calleridmanipulation/view/list",
                            {"type": "default", "start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"CallerID list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            if rows:
                self._debug_cid_fields = list(rows[0].keys())
                self._debug_cid_sample = rows[0]
            results = []
            cid = str(customer_id or "").lower()
            code_lower = (code or "").lower()
            gname = (group_name or peer_value or "").lower()
            peer_ids_lower = set(p.lower() for p in (peer_ids or []) if p)
            for row in rows:
                name = (row.get("peerID_value") or row.get("peerID") or row.get("peer")
                        or row.get("sippeer_value") or "")
                name_lower = name.lower()
                matched = (name_lower == code_lower or name_lower == cid or name_lower == gname)
                if not matched and peer_ids_lower:
                    matched = name_lower in peer_ids_lower
                if not matched:
                    continue
                results.append({
                    "id": row.get("id") or row.get("ID") or row.get("manipulation_id"),
                    "internal_exten_range_begin": row.get("internal_exten_range_begin", ""),
                    "internal_exten_range_end": row.get("internal_exten_range_end", ""),
                    # Additive fields: the desktop module only reads the two rows above,
                    # but the web UI shows the *resolved DID* (callerid_prepend applied
                    # to the internal range), which is what an operator looks for here.
                    "peerID": row.get("peerID", ""),
                    "callerid_prepend": row.get("callerid_prepend", ""),
                    "callerid_strip": row.get("callerid_strip", ""),
                    "resolved_range_begin": row.get("resolved_range_begin", ""),
                    "resolved_range_end": row.get("resolved_range_end", ""),
                })
            return results
        except Exception as e:
            self.last_error = f"search_calleridmanipulations error: {e}"
            return None

    def search_inboundroutings_by_peer(self, peer_value, customer_id="", group_name="", code="", peer_ids=None):
        try:
            resp = self.get("RESTful/index.php/v1/get/numberingplan/inboundnumber/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"Inbound list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            if rows:
                self._debug_inbound_fields = list(rows[0].keys())
                self._debug_inbound_sample = rows[0]
            results = []
            cid = str(customer_id or "").lower()
            code_lower = (code or "").lower()
            gname = (group_name or peer_value or "").lower()
            peer_ids_lower = set(p.lower() for p in (peer_ids or []) if p)
            for row in rows:
                name = (row.get("peerID_value") or row.get("peerID") or row.get("peer")
                        or row.get("sippeer_value") or "")
                name_lower = name.lower()
                matched = (name_lower == code_lower or name_lower == cid or name_lower == gname)
                if not matched and peer_ids_lower:
                    matched = name_lower in peer_ids_lower
                if not matched:
                    continue
                results.append({
                    "id": row.get("id") or row.get("ID") or row.get("routing_id"),
                    "range_begin": row.get("range_begin", ""),
                    "range_end": row.get("range_end", ""),
                    "number": row.get("number", f"{row.get('range_begin','')}-{row.get('range_end','')}"),
                })
            return results
        except Exception as e:
            self.last_error = f"search_inboundroutings error: {e}"
            return None

    def search_siptrunks_by_peerid(self, peerid_prefix, customer_id="", group_name="", code=""):
        try:
            resp = self.get("RESTful/index.php/v1/get/siptrunk/siptrunk/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"SIP Trunk list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            prefix_lower = (peerid_prefix or "").lower()
            cid = str(customer_id or "").lower()
            code_lower = (code or "").lower()
            gname = (group_name or peerid_prefix or "").lower()
            for row in rows:
                peer = row.get("peerID") or ""
                grp = str(row.get("group") or row.get("groupId") or row.get("customerId") or row.get("customer_id") or "")
                grp_lower = grp.lower()
                peer_lower = peer.lower()
                matches = (grp_lower == code_lower) or (grp_lower == cid) or (grp_lower == gname)
                if grp:
                    if not matches:
                        continue
                elif prefix_lower and not peer_lower.startswith(prefix_lower):
                    continue
                results.append({
                    "peerID": peer,
                    "port": row.get("port", ""),
                    "host": row.get("host", ""),
                    "group": grp,
                })
            return results
        except Exception as e:
            self.last_error = f"search_siptrunks error: {e}"
            return None

    def search_acl_groups_by_name(self, name_prefix, customer_id="", code=""):
        try:
            resp = self.get("RESTful/index.php/v1/get/configuration/aclgroup/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"ACL Group list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            prefix_lower = (name_prefix or "").lower()
            cid = str(customer_id or "").lower()
            code_lower = (code or "").lower()
            for row in rows:
                name = row.get("name") or ""
                name_lower = name.lower()
                eng_name = str(row.get("engName") or row.get("customer_name") or "").lower()
                row_cid = str(row.get("customer_id") or row.get("customerId") or "").lower()
                if cid:
                    if row_cid == cid:
                        results.append({
                            "group_id": row.get("acl_group_id") or row.get("group_id") or row.get("id") or row.get("ID"),
                            "name": name,
                        })
                    continue
                if prefix_lower and name_lower.startswith(prefix_lower):
                    results.append({
                        "group_id": row.get("acl_group_id") or row.get("group_id") or row.get("id") or row.get("ID"),
                        "name": name,
                    })
                    continue
                if code_lower and (name_lower.startswith(code_lower)
                                   or eng_name == code_lower
                                   or name_lower.startswith(eng_name)):
                    results.append({
                        "group_id": row.get("acl_group_id") or row.get("group_id") or row.get("id") or row.get("ID"),
                        "name": name,
                    })
                    continue
            return results
        except Exception as e:
            self.last_error = f"search_acl_groups error: {e}"
            return None

    def search_user_profiles_by_name(self, name_prefix, customer_id="", code=""):
        try:
            resp = self.get("RESTful/index.php/v1/get/user/userprofile/view/list",
                            {"start": 0, "limit": 6000})
            if resp.status_code != 200:
                self.last_error = f"User Profile list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            prefix_lower = (name_prefix or "").lower()
            cid = str(customer_id or "").lower()
            code_lower = (code or "").lower()
            for row in rows:
                name = row.get("profile_name") or ""
                name_lower = name.lower()
                row_cid = str(self._extract_group(row)).lower()
                if cid:
                    if row_cid == cid:
                        results.append({
                            "id": row.get("id") or row.get("ID") or row.get("profile_id"),
                            "profile_name": name,
                        })
                    continue
                if prefix_lower and name_lower.startswith(prefix_lower):
                    results.append({
                        "id": row.get("id") or row.get("ID") or row.get("profile_id"),
                        "profile_name": name,
                    })
                    continue
                if code_lower and name_lower.startswith(code_lower):
                    results.append({
                        "id": row.get("id") or row.get("ID") or row.get("profile_id"),
                        "profile_name": name,
                    })
                    continue
            return results
        except Exception as e:
            self.last_error = f"search_user_profiles error: {e}"
            return None

    def search_users_by_ext(self, ext_prefix, customer_id="", code=""):
        try:
            endpoint = "RESTful/index.php/v1/get/user/user/view/list"
            sort_param = '[{"property":"name","direction":"ASC"}]'
            resp = self.get(endpoint, {"start": 0, "limit": 6000, "sort": sort_param})
            if resp.status_code != 200:
                self.last_error = f"User list API HTTP {resp.status_code}"
                return None
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            results = []
            prefix_lower = ext_prefix.lower()
            code_lower = (code or "").lower()
            for row in rows:
                ext = row.get("username") or row.get("ext") or row.get("phoneLabel") or ""
                group_code = row.get("groupCode") or ""
                group_title = row.get("groupTitle") or ""
                group_desc = row.get("groupDesc") or ""
                name = row.get("name") or ""
                gid = self._extract_group(row)
                if customer_id:
                    if gid != customer_id:
                        continue
                elif code_lower and group_code.lower() != code_lower:
                    continue
                elif not (ext.lower().startswith(prefix_lower) or
                    group_code.lower().startswith(prefix_lower) or
                    group_title.lower().startswith(prefix_lower) or
                    group_desc.lower().startswith(prefix_lower) or
                    name.lower().startswith(prefix_lower)):
                    continue
                results.append({
                    "ext": ext,
                    "id": row.get("id") or row.get("ID") or ext,
                    "firstname": row.get("firstname", ""),
                    "lastname": row.get("lastname", ""),
                    "name": name,
                    "group": group_title or group_code,
                    "deter": row.get("deter", ""),
                    "type": row.get("type", ""),
                    "model": row.get("model", ""),
                    "cpe_model": row.get("cpe_model", ""),
                    "mac": row.get("mac", ""),
                })
            return results
        except Exception as e:
            self.last_error = f"search_users error: {e}"
            return None

    def get_user_detail(self, user_id):
        try:
            resp = self.get(f"RESTful/index.php/v1/get/user/user/{user_id}")
            if resp.status_code != 200:
                self.last_error = f"User detail API HTTP {resp.status_code}"
                return {}
            data = resp.json()
            d = data.get("data") or data.get("list") or data.get("rows") or data
            if isinstance(d, list):
                d = d[0] if d else {}
            return d or {}
        except Exception as e:
            self.last_error = f"get_user_detail error: {e}"
            return {}

    def post(self, endpoint, json_data=None):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.post(url, json=json_data, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"POST error: {e}"
            raise

    def post_json(self, endpoint, data):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.post(url, json=data, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"POST_JSON error: {e}"
            raise

    def delete(self, endpoint, params=None):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.delete(url, params=params, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"DELETE error: {e}"
            raise

    def delete_data(self, endpoint, data):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.delete(url, data=data, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"DELETE_DATA error: {e}"
            raise

    def delete_json(self, endpoint, json_data):
        import json as _json
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            headers = {"Content-Type": "application/json"}
            resp = self.session.delete(url, data=_json.dumps(json_data), headers=headers, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"DELETE_JSON error: {e}"
            raise

    def post_form(self, endpoint, data):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.post(url, data=data, timeout=30, verify=self.verify)
            return resp
        except Exception as e:
            self.last_error = f"POST_FORM error: {e}"
            raise
