import json

def run_caller_id_task(log_func, shared_data):
    log_func(">>> Start Execute Task 7: Caller ID Manipulation (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("❌ Not authenticated. Please login first.")
        return False

    group_name = shared_data.get("group_name", "").strip()
    if not group_name:
        log_func("❌ No group_name provided.")
        return False

    ranges_str = shared_data.get("inbound_ranges", "").strip()
    if not ranges_str:
        log_func("❌ No Inbound Ranges provided.")
        return False

    ranges = [r.strip() for r in ranges_str.split(",") if r.strip()]
    log_func(f"📋 Parsed {len(ranges)} inbound range(s) for Caller ID: {ranges}")

    def strip_leading_6(val):
        val = val.strip()
        if val.startswith("6") and len(val) > 1:
            return val[1:]
        return val

    success_count = 0
    for i, r in enumerate(ranges, 1):
        parts = [p.strip() for p in r.split("-")]
        if len(parts) == 1:
            range_begin = parts[0]
            range_end = parts[0]
            log_func(f"ℹ️ [{i}/{len(ranges)}] Single number '{r}' → treating as range {range_begin}-{range_end}")
        elif len(parts) == 2:
            range_begin = parts[0]
            range_end = parts[1]
        else:
            log_func(f"⚠️ [{i}/{len(ranges)}] Invalid range format: '{r}' (expected begin-end)")
            continue

        payload = {
            "peerID_value": group_name,
            "username_value": "",
            "manipulation_id": "",
            "manipulation_type": "default",
            "internal_exten_range_begin": strip_leading_6(range_begin),
            "internal_exten_range_end": strip_leading_6(range_end),
            "callerid_strip": "",
            "callerid_prepend": "6"
        }

        _raw = shared_data.get("custom_api_payloads", {}).get("Caller ID Manipulation", "")
        if _raw:
            try:
                import json as _j
                extra = _j.loads(_raw)
                payload.update(extra)
                log_func("📄 Merged custom API payload fields")
            except Exception as e:
                log_func(f"⚠️ Custom payload merge error: {e}")

        log_func(f"--- [{i}/{len(ranges)}] Creating Caller ID Manipulation: {r} ---")
        try:
            resp = rest_client.post(
                "RESTful/index.php/v1/post/numberingplan/calleridmanipulation",
                payload
            )
            try:
                d = resp.json()
                log_func(f"📡 Response ({resp.status_code}): {json.dumps(d, indent=2, ensure_ascii=False)}")
            except Exception:
                log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
                d = {}
            if resp.status_code == 200 and d.get("success"):
                log_func(f"✅ [{i}/{len(ranges)}] Range {r} created")
                success_count += 1
            else:
                log_func(f"❌ [{i}/{len(ranges)}] Range {r} failed")
        except Exception as e:
            log_func(f"❌ [{i}/{len(ranges)}] Range {r} error: {e}")

    log_func(f"✅ Task 7 complete: {success_count}/{len(ranges)} caller ID manipulations created")
    return success_count == len(ranges)
