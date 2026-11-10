import json

def run_acl_task(log_func, shared_data):
    log_func(">>> Start Execute Task 8: ACL Group (REST API) <<<")

    rest_client = shared_data.get("rest_client")
    if not rest_client or not rest_client.authenticated:
        log_func("Not authenticated. Please login first.")
        return False

    customer_id = shared_data.get("customer_id", "").strip()

    group_name = shared_data.get("group_name", "").strip()
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
        log_func("No Customer ID. Run Task 1 (Group) or search ID via Optional Task first.")
        return False

    if not group_name:
        log_func("No Group Name provided.")
        return False

    MANAGER_PERMS = json.dumps([
        {"access":"allow","module":"Switchboard","category":"Switchboard-FaxPanel","action":"export;use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-MailboxPanel","action":"use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-PcPresenceStatus","action":"view;edit"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-SchedulePanel","action":"use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-CallHistoryPanel","action":"export;use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-InstantMessagingPanel","action":"use"},
        {"access":"allow","module":"Configuration","category":"Configuration-ACLUser","action":"view;edit;export;lock;unlock"},
        {"access":"allow","module":"Personal","category":"Personal-All","action":"edit;view"},
        {"access":"allow","module":"Phonebook","category":"Phonebook-DepartmentalPhonebook","action":"view;add;edit;delete;export"},
        {"access":"allow","module":"Phonebook","category":"Phonebook-PersonalPhonebook","action":"view;add;edit;delete;export"},
        {"access":"allow","module":"Phonebook","category":"Phonebook-SitePhonebook","action":"view"},
        {"access":"allow","module":"Reporting","category":"Reporting-CDRReport","action":"view;export"},
        {"access":"allow","module":"Reporting","category":"Reporting-DurationReport","action":"view;export"},
        {"access":"allow","module":"Reporting","category":"Reporting-ConcurrentCallsReport","action":"view;export"},
        {"access":"allow","module":"Reporting","category":"Reporting-FaxReport","action":"view;download;resend;export"},
        {"access":"allow","module":"User","category":"User-User","action":"view;edit"},
        {"access":"allow","module":"User","category":"User-Mailbox","action":"view;add;edit;delete;download;export;playback"},
        {"access":"allow","module":"User","category":"User-frSIPMobile","action":"view;delete"},
        {"access":"allow","module":"SystemStatus","category":"SystemStatus-UserStatus","action":"view;export"},
        {"access":"allow","module":"Tools","category":"Tools-ResendEmail","action":"resend"},
        {"access":"allow","module":"NumberingPlan","category":"NumberingPlan-NumberCallForward","action":"view;add;delete"}
    ])

    USER_PERMS = json.dumps([
        {"access":"allow","module":"Switchboard","category":"Switchboard-FaxPanel","action":"export;use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-MailboxPanel","action":"use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-PcPresenceStatus","action":"view;edit"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-SchedulePanel","action":"use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-CallHistoryPanel","action":"export;use"},
        {"access":"allow","module":"Switchboard","category":"Switchboard-InstantMessagingPanel","action":"use"},
        {"access":"allow","module":"Personal","category":"Personal-All","action":"edit;view"},
        {"access":"allow","module":"Phonebook","category":"Phonebook-DepartmentalPhonebook","action":"view;add;edit;delete;export"},
        {"access":"allow","module":"Phonebook","category":"Phonebook-PersonalPhonebook","action":"view;add;edit;delete;export"},
        {"access":"allow","module":"Phonebook","category":"Phonebook-SitePhonebook","action":"view"},
        {"access":"allow","module":"User","category":"User-Mailbox","action":"view;add;edit;delete;download;export;playback"},
        {"access":"allow","module":"NumberingPlan","category":"NumberingPlan-TimeSlot","action":"view;add;edit"}
    ])

    selected = shared_data.get("acl_group_selection")
    if not selected:
        suffixes = ["_Managers", "_Supervisors", "_Users"]
    else:
        suffixes = [s if s.startswith("_") else "_" + s for s in selected]

    success_count = 0
    for suffix in suffixes:
        acl_name = group_name + suffix

        is_manager_like = suffix in ("_Managers", "_Supervisors")
        privilege = "manager" if is_manager_like else "limited"
        payload = {
            "members_value": "",
            "profile_members_value": "",
            "name": acl_name,
            "description": "",
            "group_privilege": privilege,
            "customer_id": customer_id,
            "allow_login_ip": "all",
            "default_permission": "deny",
            "permission": MANAGER_PERMS if is_manager_like else USER_PERMS,
        }

        _raw = shared_data.get("custom_api_payloads", {}).get(
            "ACL Group (Copy Existing Profiles with Managers & Users Suffix)", "")
        if _raw:
            try:
                extra = json.loads(_raw)
                payload.update(extra)
                log_func("Merged custom API payload fields from popup")
                payload["name"] = acl_name
                payload["customer_id"] = customer_id
            except Exception as e:
                log_func(f"Custom payload merge error: {e}")

        if isinstance(payload.get("permission"), list):
            payload["permission"] = json.dumps(payload["permission"])

        log_func(f"Creating ACL Group: {acl_name}")
        try:
            resp = rest_client.post_form("RESTful/index.php/post/configuration/aclgroup", payload)
            try:
                resp_json = resp.json()
                log_func(f"Server Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
                api_ok = resp_json.get("success", False)
            except Exception:
                log_func(f"Server Response ({resp.status_code}): {resp.text[:500]}")
                api_ok = False
            if resp.status_code == 200 and api_ok:
                log_func(f"ACL Group '{acl_name}' created successfully")
                success_count += 1
            else:
                log_func(f"ACL Group '{acl_name}' creation failed")
        except Exception as e:
            log_func(f"REST API error for '{acl_name}': {e}")

    return success_count == len(suffixes)
