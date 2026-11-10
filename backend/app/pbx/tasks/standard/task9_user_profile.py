import json
import time

def run_profile_task(log_func, shared_data):
    log_func(">>> Start Execute Task 9: User Profile (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("Not authenticated. Please login first.")
        return False

    group_name = shared_data.get("group_name", "").strip()
    if not group_name:
        log_func("No Group Name provided.")
        return False

    customer_id = shared_data.get("customer_id", "").strip()
    if not customer_id and group_name:
        log_func(f"No Customer ID found, searching list for group '{group_name}'...")
        try:
            found = rest_client.get_customer_id_by_name(group_name)
            if found:
                customer_id = found
                shared_data["customer_id"] = customer_id
                log_func(f"Auto-found Customer ID: {customer_id}")
                update_cb = shared_data.get("set_customer_id")
                if update_cb:
                    update_cb(customer_id)
            else:
                log_func(f"Could not find Customer ID: {rest_client.last_error}")
        except Exception as e:
            log_func(f"Auto-search error: {e}")
    if not customer_id:
        log_func("No Customer ID. Run Task 1 or search via Optional Task first.")
        return False

    prefix = shared_data.get("context_prefix", "").strip() or group_name
    call_status_name = group_name

    acl_group_id = shared_data.get("users_acl_group_id", "")
    if not acl_group_id:
        log_func("Looking up Users ACL group ID...")
        try:
            results = rest_client.search_acl_groups_by_name(group_name + "_Users")
            if results:
                acl_group_id = results[0].get("group_id", "")
                shared_data["users_acl_group_id"] = acl_group_id
                log_func(f"Found Users ACL group ID: {acl_group_id}")
        except Exception as e:
            log_func(f"ACL group lookup error: {e}")

    if not acl_group_id:
        log_func("Could not find Users ACL group ID. Run Task 8 first.")
        return False

    classes = ["Class_1", "Class_2", "Class_3", "Class_4"]
    success_count = 0

    def _make_step_id(prefix_str):
        return f"new-ext-gen{int(time.time() * 1000) % 10000000}"

    for cls in classes:
        profile_name = f"{group_name}_{cls}"
        user_context = f"{prefix}_{cls}"
        number_context = (shared_data.get("profile_number_context") or "").strip() or f"{prefix}_Internal"

        # ========== POST 1: Create User Profile (JSON) ==========
        payload1 = {
            "group": customer_id,
            "profile_name": profile_name,
            "profile_desc": "",
            "sfb_gateway_type": "video",
            "acl_group_id": acl_group_id,
            "user_acl_group_id": acl_group_id,
            "user_context": user_context,
            "user_dtmfmode": "rfc2833",
            "user_incominglimit": "0",
            "user_callgroup": "",
            "user_pickupgroup": "",
            "user_nat": "no",
            "user_call_restrict": "no",
            "user_callrecording": "0",
            "user_callrecording_quota": "0",
            "user_callrecording_policy": "0",
            "callGP_value": "",
            "pickupGP_value": "",
            "pagingGP_value": "",
            "activated": 1,
            "idd_pin_auth": "off",
            "idd_permit_other": "on",
            "rewritecallerid": "autoresolve",
            "calleridcustomname": "",
            "calleridcustomnum": "",
            "disa_status": "0",
            "disa_pin_auth": "N",
            "timezone": "global",
            "language": "GLOBAL",
            "polycom_vbp": "",
            "number_context": number_context,
            "user_maxmsg": "100",
            "user_maxsecs": "360",
            "user_delnewafterday": "30",
            "user_deloldafterday": "30",
            "user_envelope": "yes",
            "user_saycid": "yes",
            "user_hidefromdir": "no",
            "user_exit_zero": "",
            "user_exit_star": "",
            "vmDeliveryOpt": "0",
            "disableMWI": "0",
            "switchboard_voicemail": "0",
            "link_address_opt": "1",
            "link_address_opt_ip": "0",
            "link_address_opt_custom": "",
            "ntp_opt": "3",
            "ntp_opt_custom": "",
            "allowcodec_useGlobal": 1,
            "allowcodec_custom": "",
            "nat": "yes",
            "main_protocol": "udp",
            "mobile_nat": "yes",
            "extraOwnCPE": "0",
            "conferenceOption": "0",
            "conference_limit": "",
        }

        _raw = shared_data.get("custom_api_payloads", {}).get(
            "User Profile", "")
        if _raw:
            try:
                extra = json.loads(_raw)
                payload1.update(extra)
                log_func("Merged custom API payload fields from popup")
                payload1["profile_name"] = profile_name
                payload1["group"] = customer_id
                payload1["user_context"] = user_context
                payload1["number_context"] = number_context
            except Exception as e:
                log_func(f"Custom payload merge error: {e}")

        log_func(f"[{cls}] POST 1/4: Creating User Profile: {profile_name}")
        profile_id = None
        try:
            resp1 = rest_client.post("RESTful/index.php/v1/post/user/userprofile", payload1)
            try:
                resp1_json = resp1.json()
                log_func(f"POST 1 Response ({resp1.status_code}): {json.dumps(resp1_json, indent=2, ensure_ascii=False)}")
                if resp1.status_code == 200 and resp1_json.get("success"):
                    profile_id = resp1_json.get("profileId")
                    log_func(f"Profile created, ID: {profile_id}")
                else:
                    log_func(f"POST 1 failed for '{profile_name}'")
                    continue
            except Exception:
                log_func(f"POST 1 Response ({resp1.status_code}): {resp1.text[:500]}")
                continue
        except Exception as e:
            log_func(f"POST 1 REST API error: {e}")
            continue

        # ========== POST 2: Create Number Status (form-urlencoded) ==========
        step1_id = _make_step_id("dial")
        step2_id = _make_step_id("vm")
        step_data = [
            {
                "id": step1_id,
                "number_status_routing_id": "",
                "profile_number_status_routing_id": "",
                "step": 1,
                "step_type": "dial",
                "step_text": "",
                "app": "Dial",
                "parameter": "30,0,0,0,0,,,,{SELFEXT},,,0",
                "display_parameter": "",
                "follow_customer_setting": "",
                "greeting": "",
                "instruction": "",
                "callerid_num": "",
                "callerid_num_mod": "",
                "callerid_num_strip": "",
                "callerid_num_revert": "",
                "callerid_name": "",
                "callerid_name_mod": "",
                "callerid_name_strip": "",
                "callerid_name_revert": "",
            },
            {
                "id": step2_id,
                "number_status_routing_id": "",
                "profile_number_status_routing_id": "",
                "step": 2,
                "step_type": "voicemail",
                "step_text": "",
                "app": "Voicemail",
                "parameter": "{SELFVM},u",
                "display_parameter": "",
                "follow_customer_setting": "",
                "greeting": "",
                "instruction": "",
                "callerid_num": "",
                "callerid_num_mod": "",
                "callerid_num_strip": "",
                "callerid_num_revert": "",
                "callerid_name": "",
                "callerid_name_mod": "",
                "callerid_name_strip": "",
                "callerid_name_revert": "",
            },
        ]

        form2 = {
            "step": json.dumps(step_data),
            "busystep": json.dumps([]),
            "action": "createNumberStatus",
            "mobile": "",
            "extension": "",
            "id": "",
            "profile_id": str(profile_id),
            "type": "Extension",
            "owner_type": "profile",
            "status_name": call_status_name,
            "status_desc": "",
        }

        log_func(f"[{cls}] POST 2/4: Creating Number Status for profile ID {profile_id}")
        status_id = None
        try:
            resp2 = rest_client.post_form("RESTful/index.php/v1/post/numberingplan/numberstatus", form2)
            try:
                resp2_json = resp2.json()
                log_func(f"POST 2 Response ({resp2.status_code}): {json.dumps(resp2_json, indent=2, ensure_ascii=False)}")
                if resp2.status_code == 200 and resp2_json.get("success"):
                    status_id = resp2_json.get("status_id")
                    log_func(f"Number Status created, status_id: {status_id}")
                else:
                    log_func(f"POST 2 failed")
                    continue
            except Exception:
                log_func(f"POST 2 Response ({resp2.status_code}): {resp2.text[:500]}")
                continue
        except Exception as e:
            log_func(f"POST 2 REST API error: {e}")
            continue

        # ========== POST 3: Set Advanced Mode (form-urlencoded) ==========
        form3 = {
            "id": str(profile_id),
            "type": "profile",
            "mode": "advanced",
            "number_status_id": "",
        }

        log_func(f"[{cls}] POST 3/4: Setting Advanced Mode for profile ID {profile_id}")
        try:
            resp3 = rest_client.post_form("RESTful/index.php/numberingplan/number/set/status/mode", form3)
            try:
                resp3_json = resp3.json()
                log_func(f"POST 3 Response ({resp3.status_code}): {json.dumps(resp3_json, indent=2, ensure_ascii=False)}")
                if resp3.status_code == 200 and resp3_json.get("success"):
                    log_func("Advanced Mode enabled")
                else:
                    log_func("POST 3 failed")
                    continue
            except Exception:
                log_func(f"POST 3 Response ({resp3.status_code}): {resp3.text[:500]}")
                continue
        except Exception as e:
            log_func(f"POST 3 REST API error: {e}")
            continue

        # ========== POST 4: Update Timeslot Overview (form-urlencoded) ==========
        matching = [
            {
                "number_id": "",
                "number_status_id": "",
                "profile_id": "",
                "profile_number_status_id": str(status_id),
                "time_slot_id": "1",
                "time_slot_priority": "",
                "slot_name": "All-Time (Global)",
                "slot_desc": "Detail:\n - Always occur",
                "status_name": "",
                "status_desc": "",
            }
        ]

        form4 = {
            "matching": json.dumps(matching),
            "id": str(profile_id),
            "owner_type": "profile",
        }

        log_func(f"[{cls}] POST 4/4: Updating Timeslot for profile ID {profile_id}")
        try:
            resp4 = rest_client.post_form("RESTful/index.php/numberingplan/number/update/timeslot/overview", form4)
            try:
                resp4_json = resp4.json()
                log_func(f"POST 4 Response ({resp4.status_code}): {json.dumps(resp4_json, indent=2, ensure_ascii=False)}")
                if resp4.status_code == 200 and resp4_json.get("success"):
                    log_func("Timeslot updated successfully")
                else:
                    log_func("POST 4 failed")
                    continue
            except Exception:
                log_func(f"POST 4 Response ({resp4.status_code}): {resp4.text[:500]}")
                continue
        except Exception as e:
            log_func(f"POST 4 REST API error: {e}")
            continue

        log_func(f"[{cls}] All 4 POSTs completed for '{profile_name}'")
        success_count += 1

    log_func(f"User Profile task completed: {success_count}/{len(classes)} profiles")
    return success_count == len(classes)
