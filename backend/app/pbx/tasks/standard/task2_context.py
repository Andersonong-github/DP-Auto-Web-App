import json

def run_context_task(log_func, shared_data):
    log_func(">>> Start Execute Task 2: Context (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("❌ Not authenticated. Please login first.")
        return False

    customer_id = shared_data.get("customer_id", "").strip()

    if not customer_id:
        group_name = shared_data.get("group_name", "").strip()
        if group_name:
            log_func(f"🔍 No Customer ID found, searching list for group '{group_name}'...")
            try:
                found = rest_client.get_customer_id_by_name(group_name)
                if found:
                    customer_id = found
                    shared_data["customer_id"] = customer_id
                    log_func(f"✅ Auto-found Customer ID: {customer_id}")
                    update_cb = shared_data.get("set_customer_id")
                    if update_cb:
                        update_cb(customer_id)
                else:
                    log_func(f"⚠️ Could not find Customer ID: {rest_client.last_error}")
            except Exception as e:
                log_func(f"⚠️ Auto-search error: {e}")

    if not customer_id:
        log_func("❌ No Customer ID. Run Task 1 (Group) or search ID via Optional Task first.")
        return False

    base_name = shared_data.get("context_prefix", "").strip()
    if not base_name:
        base_name = shared_data.get("group_name", "").strip()
    if not base_name:
        log_func("❌ No context_prefix or group_name provided.")
        return False

    prefix = base_name[:-1] if base_name.endswith("_") else base_name
    suffixes = ["_Internal", "_Fixed", "_Mobile", "_IDD"]

    # Parse custom payload: list = full override, dict = extra fields
    custom_list = None
    extra_fields = {}
    _raw = shared_data.get("custom_api_payloads", {}).get("Context (Auto suffix _Fixed,Internal,Mobile&IDD)", "")
    if _raw:
        try:
            _p = json.loads(_raw)
            if isinstance(_p, list):
                custom_list = _p
                log_func(f"📄 Using custom context list ({len(custom_list)} items)")
            elif isinstance(_p, dict):
                extra_fields = _p
                log_func("📄 Merging extra fields into all contexts")
        except Exception as e:
            log_func(f"⚠️ Custom payload parse error: {e}")

    success_count = 0

    def create_one(payload):
        nonlocal success_count
        cid = payload.get("contextID", "")
        log_func(f"--- Creating Context: {cid} ---")
        try:
            resp = rest_client.post("RESTful/index.php/v1/post/numberingplan/context", payload)
            try:
                resp_json = resp.json()
                log_func(f"📡 Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
            except Exception:
                log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
            if resp.status_code == 200:
                log_func(f"✅ {cid} created successfully")
                success_count += 1
            else:
                log_func(f"❌ {cid} failed")
        except Exception as e:
            log_func(f"❌ {cid} error: {e}")

    if custom_list:
        for item in custom_list:
            pl = {
                "contextID": item.get("contextID", ""),
                "contextTitle": item.get("contextTitle", ""),
                "group": item.get("group", customer_id),
                "contextDesc": item.get("contextDesc", "")
            }
            create_one(pl)
    else:
        for suffix in suffixes:
            ctx_id = f"{prefix}{suffix}"
            pl = {
                "contextID": ctx_id,
                "contextTitle": ctx_id,
                "group": customer_id,
                "contextDesc": ""
            }
            if extra_fields:
                pl.update(extra_fields)
            create_one(pl)

    log_func(f"✅ Task 2 complete: {success_count}/{len(custom_list) if custom_list else 4} contexts created")
    return success_count == (len(custom_list) if custom_list else 4)
