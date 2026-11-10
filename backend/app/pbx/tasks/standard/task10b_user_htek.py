import json

def run_user_htek_task(log_func, shared_data):
    log_func(">>> Start Execute Task: User (Htek Mac based Only) (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("Not authenticated. Please login first.")
        return False

    ext_range = shared_data.get("user_ext", "").strip()
    if not ext_range:
        log_func("No User Extension / Extension Range provided.")
        return False

    from ...ext_parser import parse_ext_range
    exts = parse_ext_range(ext_range)

    if not exts:
        log_func("No valid extensions to create.")
        return False

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

    acl_group_id = shared_data.get("users_acl_group_id", "")
    if not acl_group_id:
        log_func("Looking up Users ACL group ID for Htek...")
        try:
            results = rest_client.search_acl_groups_by_name(group_name + "_Users")
            if results:
                acl_group_id = results[0].get("group_id", "")
                shared_data["users_acl_group_id"] = acl_group_id
                log_func(f"Found Users ACL group ID: {acl_group_id}")
        except Exception as e:
            log_func(f"ACL group lookup error: {e}")
    if not acl_group_id:
        log_func("Could not find ACL group ID. Run Task 8 first.")
        return False

    prefix = shared_data.get("context_prefix", "").strip() or group_name
    perm_gp = f"{prefix}_Class_4"

    mac_data_list = shared_data.get("htek_mac_data", [])
    if len(mac_data_list) != len(exts):
        log_func(f"MAC data count ({len(mac_data_list)}) doesn't match extension count ({len(exts)}).")
        return False

    append_record = shared_data.get("append_user_record")
    success_count = 0
    total = len(exts)

    for i, ext in enumerate(exts):
        last4 = ext[-4:]

        if i == 0:
            lastname = "Manager"
        else:
            lastname = f"User {i}"

        mac_info = mac_data_list[i]

        payload = {
            "ext": ext,
            "firstname": f"User{last4}",
            "lastname": lastname,
            "firstname_p": "",
            "lastname_p": "",
            "group": customer_id,
            "email": "",
            "empolyee_id": "",
            "phoneLabel": last4,
            "mobile": "",
            "mobile_express": "",
            "sms1": "",
            "sms2": "",
            "profile": profile_id,
            "aclGroup": acl_group_id,
            "permissionGP": perm_gp,
            "call_restrict": "no",
            "call_waiting": "0",
            "callRecording_type": "1",
            "callRecording_quota": "0",
            "callRecording_policy": "0",
            "callGP": [""],
            "pickupGP": [""],
            "pagingGP": [""],
            "timezone": "global",
            "polycom_vbp": "",
            "language": "GLOBAL",
            "voicemail_maxmsg": "100",
            "voicemail_maxmessage": "360",
            "voicemail_delnewafterday": "30",
            "voicemail_deloldafterday": "30",
            "voicemail_say_header": "yes",
            "voicemail_say_callerid": "yes",
            "voicemail_hidefromdir": "no",
            "voicemail_exit_zero": "",
            "voicemail_exit_star": "",
            "vmDeliveryOpt": "0",
            "disableMWI": "0",
            "switchboard_voicemail": "1",
            "link_address_opt": "1",
            "link_address_opt_custom": "",
            "link_address_opt_ip": "0",
            "allowcodec_useGlobal": "1",
            "allowcodec_custom": "",
            "nat": "yes",
            "mobile_nat": "yes",
            "main_protocol": "udp",
            "ntp_opt": "3",
            "ntp_opt_custom": "",
            "sla": "0",
            "bargein": "",
            "sga": "",
            "bargeall": "0",
            "sgabargeinuser": [],
            "deter": "1",
            "cpe_model": "",
            "analogueLine": "",
            "mac": mac_info["mac"],
            "mac_select": mac_info["mac_select"],
            "type": "Htek",
            "model": mac_info["model"].upper(),
            "linenum": "1",
            "room_sys_model": "",
            "room_sys_ip": "",
            "avaya_model": "",
            "aastra_model": "",
            "ip": "2",
            "survivequintum": "",
            "autoAnswer": "2",
            "hotdeskphone": "0",
            "eyebeam_license": "",
            "nokia_mobile_number": "",
            "nokia_mobile_server_ip": "",
            "extraOwnCPE": "0",
            "conferenceOption": "0",
            "sip_h323": "0",
            "h323_server_addr": "",
            "h323_server_port": "",
            "h323_server_expires": "",
            "cyberdata_dialnumber": "",
            "cyberdata_dialexten": "",
            "cyberdata_dialid": "",
            "checkpg": "Profiled",
            "checkacl": "Profiled",
            "checkcgroup": "Profiled",
            "checkpugroup": "Profiled",
            "checkpagroup": "Profiled",
            "checkwaiting": "0",
            "checklang": "Profiled",
            "checkvmopt": "Profiled",
            "checkcodec": "Profiled",
            "checknat": "yes",
            "checkmobile_nat": "Profiled",
            "checkextra": "",
            "checkconf": "",
            "checkrecord": "Profiled",
            "checkrecordquota": "Profiled",
            "checkrecordpolicy": "Profiled",
            "checkdisablemwi": "Profiled",
            "checkswitchboardvoicemail": "Profiled",
            "checkmain_protocol": "Profiled",
            "checkcall_restrict": "Profiled",
            "checkntp_opt": "Profiled",
            "checklink_address_opt": "Profiled",
            "checktimezone": "Profiled",
            "checkpolycom_vbp": "Profiled",
            "checkmaxmsg": "Profiled",
            "checkmaxsecs": "Profiled",
            "checkenvelope": "Profiled",
            "checksaycid": "Profiled",
            "checkhidefromdir": "Profiled",
            "checkdelnewafterday": "Profiled",
            "checkdeloldafterday": "Profiled",
            "checkexitzero": "",
            "checkexitstar": "",
            "activated": "1",
            "idd_pin_auth": "0",
            "idd_permit_other": "1",
            "rewritecallerid": "autoresolve",
            "calleridcustomnum": "",
            "calleridcustomname": "",
            "checkstatus": "Profiled",
            "checkcallerid": "Profiled",
            "checkpinAuth": "Profiled",
            "disa_callerid": ext,
            "disa_status": "0",
            "disa_pin_auth": "N",
            "checkdisastatus": "Profiled",
            "checkdisapin": "Profiled",
            "sfb_target": "",
            "checksfbgatewaytype": "Profiled",
            "sfb_gateway_type": "video",
        }

        _raw = shared_data.get("custom_api_payloads", {}).get(
            "User (Htek Mac based Only)", "")
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

        log_func(f"Creating Htek User: {ext} ({lastname})")
        try:
            resp = rest_client.post("RESTful/index.php/v2/post/user/user", payload)
            try:
                resp_json = resp.json()
                log_func(f"Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
                api_ok = resp_json.get("success", False)
                if resp.status_code == 200 and api_ok:
                    log_func(f"Htek User '{ext}' created successfully")
                    success_count += 1
                    pin_data = resp_json.get("pin", {})
                    gen_login_pwd = pin_data.get("login_pw", "")
                    gen_pin = pin_data.get("user_pin", "")
                    log_func(f"Auto-generated -> login_password: {gen_login_pwd}, password: {gen_pin}")
                    if append_record:
                        append_record(ext, gen_login_pwd, gen_pin)
                else:
                    log_func(f"Htek User '{ext}' creation failed")
            except Exception:
                log_func(f"Response ({resp.status_code}): {resp.text[:500]}")
        except Exception as e:
            log_func(f"REST API error for '{ext}': {e}")

    log_func(f"Created {success_count}/{total} Htek users")
    return success_count == total
