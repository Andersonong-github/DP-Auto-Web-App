import json

def run_group_task(log_func, shared_data):
    log_func(">>> Start Execute Task 1: Group (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("❌ Not authenticated. Please login first using the 'Login & Save Token' button.")
        return False

    g_name = shared_data.get('group_name', '')
    g_code = shared_data.get('group_code', '')
    max_limit = str(shared_data.get('max_concurrent', '10'))

    payload = {
        "code": g_code,
        "engName": g_name,
        "chiName": "",
        "email": "",
        "greeting": "",
        "instruction": "",
        "locationAddress": "",
        "locationName": "e",
        "staff_value": "",
        "customer_value": "",
        "maxConcurrentCalls": max_limit,
        "registerUserCount": max_limit,
        "CCAgentCount": "0",
        "OCCAgentCount": "0",
        "SFBAccountCount": "0",
        "PTTGroupCount": "0"
    }

    # Merge custom fields from popup editor
    _raw = shared_data.get("custom_api_payloads", {}).get("Group", "")
    if _raw:
        try:
            import json as _j
            extra = _j.loads(_raw)
            payload.update(extra)
            log_func("📄 Merged custom API payload fields from popup")
        except Exception as e:
            log_func(f"⚠️ Custom payload merge error: {e}")

    log_func(f"Creating Group via API: {g_name} ({g_code}), max={max_limit}")
    try:
        resp = rest_client.post("RESTful/index.php/v2/post/customer/customer", payload)
        resp_json = None
        try:
            resp_json = resp.json()
            log_func(f"📡 Server Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
        except Exception:
            log_func(f"📡 Server Response ({resp.status_code}): {resp.text[:500]}")
        if resp.status_code == 200 and resp_json and resp_json.get("success", False):
            log_func("✅ Group created successfully via REST API")

            # Auto-fetch customer ID for subsequent tasks
            log_func("🔍 Fetching Customer ID from customer list...")
            try:
                list_resp = rest_client.get(
                    "RESTful/index.php/v2/get/customer/customer/view/list",
                    {"start": 0, "limit": 6000}
                )
                list_data = list_resp.json()
                log_func(f"📡 List API Response: {json.dumps(list_data, indent=2, ensure_ascii=False)[:2000]}")

                rows = list_data.get("list") or list_data.get("rows") or list_data.get("data") or []
                log_func(f"🔍 Searching {len(rows)} customers for engName='{g_name}'")

                found_id = None
                for row in rows:
                    name = row.get("engName") or row.get("name") or row.get("customerName") or ""
                    if name == g_name:
                        found_id = row.get("customerId") or row.get("id") or row.get("ID")
                        log_func(f"✅ Matched! name='{name}', id={found_id}")
                        break

                if found_id:
                    shared_data["customer_id"] = found_id
                    log_func(f"✅ Found Customer ID: {found_id}")
                    update_cb = shared_data.get("set_customer_id")
                    if update_cb:
                        update_cb(found_id)
                else:
                    log_func("⚠️ Could not find Customer ID in list. Try entering it manually.")
                    # Log first row keys to help debug
                    if rows:
                        log_func(f"📋 First row keys: {list(rows[0].keys())}")
                        log_func(f"📋 First row values: {json.dumps(rows[0], indent=2, ensure_ascii=False)}")
            except Exception as e:
                log_func(f"⚠️ Error fetching Customer ID: {e}")

            return True
        else:
            log_func(f"❌ Group creation failed")
            return False
    except Exception as e:
        log_func(f"❌ REST API error: {e}")
        return False
