import json

def run_sip_task(log_func, shared_data):
    log_func(">>> Start Execute Task 4: SIP Trunk (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("❌ Not authenticated. Please login first.")
        return False

    customer_id = shared_data.get("customer_id", "").strip()
    if not customer_id:
        group_name = shared_data.get("group_name", "").strip()
        if group_name:
            log_func(f"🔍 No Customer ID, searching for group '{group_name}'...")
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
        log_func("❌ No Customer ID. Run Task 1 or search via Optional Task first.")
        return False

    group_name = shared_data.get("group_name", "").strip()
    host_ip = shared_data.get("host_ip", "").strip()
    port = shared_data.get("port", "5060").strip()

    # Context value = perm_group_prefix_Class_1
    perm_prefix = shared_data.get("perm_group_prefix", "").strip()
    if not perm_prefix:
        perm_prefix = shared_data.get("context_prefix", "").strip()
    if not perm_prefix:
        perm_prefix = group_name
    ctx_base = perm_prefix[:-1] if perm_prefix.endswith("_") else perm_prefix
    context_value = f"{ctx_base}_Class_1"

    payload = {
        "allowcodec_value": "alaw,ulaw,g729",
        "group": customer_id,
        "peerID": group_name,
        "pronunciation": group_name,
        "host": host_ip,
        "port": port,
        "frsipPBX": "0",
        "main_protocol": "udp",
        "nat": "0",
        "inviteRequireAuth": "0",
        "password": "",
        "registration_extension": "",
        "registration_expires": "",
        "reg_server_option": "0",
        "call_restrict": "no",
        "context": context_value,
        "dtmfmode": "rfc2833",
        "copyCidNameToNum": "no",
        "routingMethod": "VoIP+PSTN",
        "fromdomain": "",
        "insecure": "invite",
        "allowsipinfo": "1",
        "canreinvite": "0",
        "promiscredir": "0",
        "qualify": "1",
        "ignoresdpversion": "no",
        "support183": "yes",
        "sessionTimers": "0",
        "sessionExpires": "",
        "faxCodec": "t38",
        "t38FaxMaxDatagram": "",
        "outboundproxy": "",
        "pai": "0",
        "host_backup": "",
        "port_backup": ""
    }

    _raw = shared_data.get("custom_api_payloads", {}).get("SIP Trunk", "")
    if _raw:
        try:
            import json as _j
            extra = _j.loads(_raw)
            payload.update(extra)
            log_func("📄 Merged custom API payload fields")
        except Exception as e:
            log_func(f"⚠️ Custom payload merge error: {e}")

    log_func(f"Creating SIP Trunk: {group_name} ({host_ip}:{port}), group={customer_id}, context={context_value}")
    try:
        resp = rest_client.post("RESTful/index.php/v1/post/siptrunk/siptrunk", payload)
        try:
            resp_json = resp.json()
            log_func(f"📡 Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
        except Exception:
            log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
        if resp.status_code == 200:
            log_func("✅ SIP Trunk created successfully")
            return True
        else:
            log_func("❌ SIP Trunk creation failed")
            return False
    except Exception as e:
        log_func(f"❌ REST API error: {e}")
        return False
