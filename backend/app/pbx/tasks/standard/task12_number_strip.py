import json
import time

def run_number_strip_task(log_func, shared_data):
    log_func(">>> Start Execute Task 12: Number (Strip Digits) (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("Not authenticated. Please login first.")
        return False

    group_name = shared_data.get("group_name", "").strip()
    customer_id = shared_data.get("customer_id", "").strip()
    if not customer_id and group_name:
        log_func(f"No Customer ID found, searching for group '{group_name}'...")
        try:
            found = rest_client.get_customer_id_by_name(group_name)
            if found:
                customer_id = found
                shared_data["customer_id"] = customer_id
                log_func(f"Auto-found Customer ID: {customer_id}")
        except Exception as e:
            log_func(f"Auto-search error: {e}")
    if not customer_id:
        log_func("No Customer ID. Run Task 1 first.")
        return False

    prefix = shared_data.get("context_prefix", "").strip() or group_name

    ext_range = shared_data.get("user_ext", "").strip()
    if not ext_range:
        log_func("No User Extension / Extension Range provided.")
        return False

    from ...ext_parser import parse_ext_groups
    groups = parse_ext_groups(ext_range)

    if not groups:
        log_func("No valid extensions to process.")
        return False

    context = f"{prefix}_Internal"
    sel_ctx = (shared_data.get("number_strip_context") or "").strip()
    if sel_ctx:
        context = sel_ctx
        log_func(f"Context: {context} (from Task 12 Context dropdown)")

    # Resolve the context name against what actually exists on the server
    # (underscore-insensitive), e.g. 'Xxx_SetiaAlam_Internal' ->
    # 'Xxx_Setia_Alam_Internal' when the context_prefix differs in spacing.
    try:
        _ctx_search = (rest_client.search_contexts_by_group(customer_id, group_name)
                       if hasattr(rest_client, "search_contexts_by_group") else None)
        if _ctx_search:
            _existing = {str(c.get("contextID") or "").strip()
                         for c in _ctx_search if c.get("contextID")}
            if context not in _existing:
                norm = lambda s: str(s).replace("_", "").lower()
                match = next((c for c in sorted(_existing) if norm(c) == norm(context)), None)
                if match:
                    log_func(f"ℹ️ Context: matched existing '{match}' (from '{context}')")
                    context = match
                else:
                    log_func(f"⚠️ Context '{context}' does NOT exist for this customer — "
                             f"run Task 2 (Context) first or check the context_prefix.")
    except Exception:
        pass

    log_func(f"📋 Parsed {len(groups)} extension group(s): "
             f"{[g[0] + '-' + g[-1] for g in groups]}")

    def _build_pattern(exts):
        first_ext = exts[0]
        last_ext = exts[-1]

        # ---- Build number pattern from last 4 digits ----
        last4_start = first_ext[-4:] if len(first_ext) >= 4 else first_ext
        last4_end = last_ext[-4:] if len(last_ext) >= 4 else last_ext
        min_len = min(len(last4_start), len(last4_end))

        number_suffix = ""
        for i in range(min_len):
            if last4_start[i] != last4_end[i]:
                number_suffix += "X" * (min_len - i)
                break
            else:
                number_suffix += last4_start[i]
        if not number_suffix:
            number_suffix = last4_start

        number_pattern = f"_{number_suffix}"

        # ---- Goto prefix (without last 4 and without leading 6) ----
        step3_prefix = first_ext[:-4] if len(first_ext) > 4 else ""

        return number_pattern, step3_prefix

    success_count = 0
    total = len(groups)

    for gi, exts in enumerate(groups, 1):
        number_pattern, step3_prefix = _build_pattern(exts)
        number_name = f"{group_name} Strip Digit"

        log_func(f"--- [{gi}/{total}] Group: {exts[0]}-{exts[-1]} ---")
        log_func(f"Number pattern: {number_pattern}")
        log_func(f"Number name: {number_name}")
        log_func(f"Context: {context}")
        log_func(f"Goto prefix: {step3_prefix}")

        # ========== STEP 1: POST JSON create number ==========
        payload1 = {
            "action": "createNumber",
            "id": "",
            "crm": "0",
            "inbound": "0",
            "type": "Number",
            "number": number_pattern,
            "number_static": "",
            "callerid_matching": "",
            "number_name": number_name,
            "number_name_static": "",
            "number_desc": "",
            "group": customer_id,
            "context": context,
            "call_recording": "no",
            "idd_account": "",
        }

        _raw = shared_data.get("custom_api_payloads", {}).get("Number (Strip Digits)", "")
        if _raw:
            try:
                extra = json.loads(_raw)
                payload1.update(extra)
                log_func("📄 Merged custom API payload fields from popup")
                payload1["number"] = number_pattern
                payload1["group"] = customer_id
                payload1["context"] = context
            except Exception as e:
                log_func(f"⚠️ Custom payload merge error: {e}")

        log_func(f"STEP 1/3: Creating number: {number_pattern}")
        number_id = None
        try:
            resp1 = rest_client.post("RESTful/index.php/numberingplan/number", payload1)
            try:
                resp1_json = resp1.json()
                log_func(f"STEP 1 Response ({resp1.status_code}): {json.dumps(resp1_json, indent=2, ensure_ascii=False)}")
                if resp1.status_code == 200 and resp1_json.get("success"):
                    number_id = resp1_json.get("id")
                    log_func(f"Number created, ID: {number_id}")
                else:
                    log_func("STEP 1 failed")
                    continue
            except Exception:
                log_func(f"STEP 1 Response ({resp1.status_code}): {resp1.text[:500]}")
                continue
        except Exception as e:
            log_func(f"STEP 1 REST API error: {e}")
            continue

        if not number_id:
            log_func("No number ID returned, aborting this group.")
            continue

        # ========== STEP 2: POST form-urlencoded create number status ==========
        step_id = f"new-ext-gen{int(time.time() * 1000) % 10000000}"
        step_data = [
            {
                "id": step_id,
                "number_status_routing_id": "",
                "profile_number_status_routing_id": "",
                "step": 1,
                "step_type": "goto_context",
                "step_text": "",
                "app": "Goto",
                "parameter": f"{step3_prefix},,{context}",
                "display_parameter": "",
                "follow_customer_setting": "",
                "greeting": "",
                "instruction": "",
                "callerid_num": "0",
                "callerid_num_mod": "",
                "callerid_num_strip": "",
                "callerid_num_revert": False,
                "callerid_name": "0",
                "callerid_name_mod": "",
                "callerid_name_strip": "",
                "callerid_name_revert": False,
            }
        ]

        form2 = {
            "step": json.dumps(step_data),
            "busystep": json.dumps([]),
            "action": "createNumberStatus",
            "mobile": "",
            "extension": "",
            "id": "",
            "number_id": str(number_id),
            "type": "Number",
            "owner_type": "",
            "status_name": "Strip Digit",
            "status_desc": "",
        }

        log_func(f"STEP 2/3: Creating Number Status for number ID {number_id}")
        status_id = None
        try:
            resp2 = rest_client.post_form("RESTful/index.php/v1/post/numberingplan/numberstatus", form2)
            try:
                resp2_json = resp2.json()
                log_func(f"STEP 2 Response ({resp2.status_code}): {json.dumps(resp2_json, indent=2, ensure_ascii=False)}")
                if resp2.status_code == 200 and resp2_json.get("success"):
                    status_id = resp2_json.get("status_id")
                    log_func(f"Number Status created, status_id: {status_id}")
                else:
                    log_func("STEP 2 failed")
                    continue
            except Exception:
                log_func(f"STEP 2 Response ({resp2.status_code}): {resp2.text[:500]}")
                continue
        except Exception as e:
            log_func(f"STEP 2 REST API error: {e}")
            continue

        if not status_id:
            log_func("No status_id returned, aborting this group.")
            continue

        # ========== STEP 3: POST form-urlencoded set status mode ==========
        form3 = {
            "id": str(number_id),
            "type": "number",
            "mode": "simple",
            "number_status_id": str(status_id),
        }

        log_func(f"STEP 3/3: Setting Simple Mode for number ID {number_id}")
        try:
            resp3 = rest_client.post_form("RESTful/index.php/numberingplan/number/set/status/mode", form3)
            try:
                resp3_json = resp3.json()
                log_func(f"STEP 3 Response ({resp3.status_code}): {json.dumps(resp3_json, indent=2, ensure_ascii=False)}")
                if resp3.status_code == 200 and resp3_json.get("success"):
                    log_func("Simple Mode enabled successfully")
                else:
                    log_func("STEP 3 failed")
                    continue
            except Exception:
                log_func(f"STEP 3 Response ({resp3.status_code}): {resp3.text[:500]}")
                continue
        except Exception as e:
            log_func(f"STEP 3 REST API error: {e}")
            continue

        log_func(f"[{gi}/{total}] Number '{number_pattern}' (strip {step3_prefix}) created successfully")
        success_count += 1

    log_func(f"Task 12 complete: {success_count}/{total} numbers (strip digits) created")
    return success_count == total
