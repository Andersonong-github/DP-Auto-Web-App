import json

def run_user_task(log_func, shared_data):
    log_func(">>> Start Execute Task 10: User (Mobility Apps) (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("Not authenticated. Please login first.")
        return False

    ext_range = shared_data.get("user_ext", "").strip()
    if not ext_range:
        log_func("No User Extension / Extension Range provided.")
        return False

    from ...ext_parser import parse_ext_groups
    groups = parse_ext_groups(ext_range, strip_six=False)

    if not groups:
        log_func("No valid extensions to create.")
        return False

    total = sum(len(g) for g in groups)
    log_func(f"📋 Parsed {len(groups)} extension group(s): "
             f"{[g[0] + '-' + g[-1] for g in groups]}")

    customer_id = shared_data.get("customer_id", "").strip()
    group_name = shared_data.get("group_name", "").strip()
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

    profile_id = shared_data.get("class3_profile_id", "")
    if not profile_id and group_name:
        log_func("Looking up Class_3 User Profile...")
        try:
            results = rest_client.search_user_profiles_by_name(group_name + "_Class_3")
            if results:
                profile_id = results[0].get("id", "")
                shared_data["class3_profile_id"] = profile_id
                log_func(f"Found Class_3 Profile ID: {profile_id}")
        except Exception as e:
            log_func(f"Profile lookup error: {e}")
    if not profile_id:
        log_func("Could not find Class_3 User Profile. Run Task 9 first.")
        return False

    append_record = shared_data.get("append_user_record")
    success_count = 0
    usernames = shared_data.get("usernames", [])
    emails = shared_data.get("emails", [])
    flat_index = 0

    for gi, exts in enumerate(groups, 1):
        log_func(f"--- [{gi}/{len(groups)}] Extension group: {exts[0]}-{exts[-1]} ---")
        for i, ext in enumerate(exts):
            last4 = ext[-4:]

            if usernames and flat_index < len(usernames) and usernames[flat_index].strip():
                from utils.name_split import split_name
                first_name, last_name = split_name(usernames[flat_index])
            elif i == 0:
                first_name, last_name = f"User{last4}", "Manager"
            else:
                first_name, last_name = f"User{last4}", f"User {i}"

            if emails and flat_index < len(emails) and emails[flat_index].strip():
                user_email = emails[flat_index].strip()
            else:
                user_email = ""
            flat_index += 1

            payload = {
                "action": "newUser",
                "ext": ext,
                "firstname": first_name,
                "lastname": last_name,
                "group": customer_id,
                "profile": profile_id,
                "callRecording_quota": "0",
                "callRecording_policy": "0",
                "deter": "0",
                "callGP_value": "",
                "pickupGP_value": "",
                "pagingGP_value": "",
                "allowcodec_custom_value": "",
                "sgabargeinuser_value": "",
                "disa_callerid": "",
                "firstname_p": first_name,
                "lastname_p": last_name,
                "email": user_email,
                "empolyee_id": "",
                "phoneLabel": last4,
                "mobile": "",
                "mobile_express": "",
                "sms1": "",
                "sms2": "",
                "sfb_target": "",
                "checksfbgatewaytype": "Profiled",
                "sfb_gateway_type": "",
                "mac": "",
                "mac_select": "",
                "type": "",
                "model": "",
                "linenum": "1",
                "cyberdata_dialid": "security",
                "cyberdata_dialnumber": "",
                "cyberdata_dialexten": "",
                "sip_h323": "",
                "ip": "2",
                "survivequintum": "",
                "h323_server_addr": "",
                "h323_server_port": "",
                "h323_server_expires": "",
                "hotdeskphone": "0",
                "autoAnswer": "2",
                "nat": "yes",
                "checkacl": "Profiled",
                "checkpg": "Profiled",
                "checkcall_restrict": "Profiled",
                "checkwaiting": "Profiled",
                "checkrecord": "Profiled",
                "checkcgroup": "Profiled",
                "checkpugroup": "Profiled",
                "checkpagroup": "Profiled",
                "checkstatus": "Profiled",
                "checkpinAuth": "Profiled",
                "checkcallerid": "Profiled",
                "checkdisastatus": "Profiled",
                "checkdisapin": "Profiled",
                "disa_callerid_match": "",
                "checktimezone": "Profiled",
                "checklang": "Profiled",
                "checkpolycom_vbp": "Profiled",
                "checkmaxmsg": "Profiled",
                "checkmaxsecs": "Profiled",
                "checkdelnewafterday": "Profiled",
                "checkdeloldafterday": "Profiled",
                "checkenvelope": "Profiled",
                "checksaycid": "Profiled",
                "checkhidefromdir": "Profiled",
                "checkexitzero": "Profiled",
                "checkexitstar": "Profiled",
                "checkvmopt": "Profiled",
                "checkdisablemwi": "Profiled",
                "checkswitchboardvoicemail": "Profiled",
                "checklink_address_opt": "Profiled",
                "checkntp_opt": "Profiled",
                "checkcodec": "Profiled",
                "checknat": "yes",
                "checkmain_protocol": "Profiled",
                "checkmobile_nat": "Profiled",
                "sla": "0",
                "checkextra": "Profiled",
                "checkconf": "Profiled",
            }

            _raw = shared_data.get("custom_api_payloads", {}).get(
                "User (Mobility Apps Only)", "")
            if _raw:
                try:
                    extra = json.loads(_raw)
                    payload.update(extra)
                    log_func("Merged custom API payload fields from popup")
                    payload["ext"] = ext
                    payload["group"] = customer_id
                    payload["profile"] = profile_id
                except Exception as e:
                    log_func(f"Custom payload merge error: {e}")

            log_func(f"Creating User: {ext} ({last_name})")
            try:
                resp = rest_client.post("RESTful/index.php/v2/post/user/user", payload)
                try:
                    resp_json = resp.json()
                    log_func(f"Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
                    api_ok = resp_json.get("success", False)
                    if resp.status_code == 200 and api_ok:
                        log_func(f"User '{ext}' created successfully")
                        success_count += 1
                        pin_data = resp_json.get("pin", {})
                        gen_login_pwd = pin_data.get("login_pw", "")
                        gen_pin = pin_data.get("user_pin", "")
                        log_func(f"Auto-generated -> login_password: {gen_login_pwd}, password: {gen_pin}")
                        if append_record:
                            append_record(ext, gen_login_pwd, gen_pin)
                    else:
                        log_func(f"User '{ext}' creation failed")
                except Exception:
                    log_func(f"Response ({resp.status_code}): {resp.text[:500]}")
            except Exception as e:
                log_func(f"REST API error for '{ext}': {e}")

    log_func(f"Created {success_count}/{total} users")
    return success_count == total
