import json

MANAGER_FEATURES = [
    "makeCall", "getUserDevice", "checkFeatures", "frsipMobileLogin"
]

def run_acl_user_task(log_func, shared_data):
    log_func(">>> Start Execute Task 11: ACL User (REST API) <<<")

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
                update_cb = shared_data.get("set_customer_id")
                if update_cb:
                    update_cb(customer_id)
        except Exception as e:
            log_func(f"Auto-search error: {e}")

    if not customer_id:
        log_func("No Customer ID. Run Task 1 first.")
        return False
    if not group_name:
        log_func("No Group Name provided.")
        return False

    ext_range = shared_data.get("user_ext", "").strip()
    if not ext_range:
        log_func("No User Extension / Extension Range provided.")
        return False

    from ...ext_parser import parse_ext_groups
    groups = parse_ext_groups(ext_range)

    if not groups:
        log_func("No valid extensions to process.")
        return False

    log_func(f"📋 Parsed {len(groups)} extension group(s): "
             f"{[g[0] + '-' + g[-1] for g in groups]}")

    # ========== GET #2: ACL group list → find Managers/Users IDs + customer_id ==========
    managers_acl_id = None
    users_acl_id = None
    log_func("Fetching ACL group list...")
    try:
        resp = rest_client.get("RESTful/index.php/v1/get/configuration/aclgroup/view/list",
                               {"start": 0, "limit": 6000})
        if resp.status_code == 200:
            data = resp.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            for row in rows:
                name = row.get("name", "") or ""
                gid = row.get("id") or row.get("acl_group_id") or row.get("group_id") or ""
                eng = row.get("engName") or row.get("customer_name") or ""
                row_customer = str(row.get("customer_id") or "")
                if eng == group_name and row_customer:
                    customer_id = row_customer
                    shared_data["customer_id"] = customer_id
                if name.lower() == f"{group_name}_managers".lower():
                    managers_acl_id = gid
                elif name.lower() == f"{group_name}_users".lower():
                    users_acl_id = gid
        else:
            log_func(f"ACL group list HTTP {resp.status_code}")
    except Exception as e:
        log_func(f"Error fetching ACL group list: {e}")

    if not managers_acl_id:
        log_func(f"Could not find ACL group '{group_name}_Managers'. Run Task 8 first.")
        return False
    if not users_acl_id:
        log_func(f"Could not find ACL group '{group_name}_Users'. Run Task 8 first.")
        return False
    log_func(f"ACL groups: _Managers ID={managers_acl_id}, _Users ID={users_acl_id}, customer_id={customer_id}")

    success_count = 0
    total = 0
    for g in groups:
        total += len(g)

    for gi, exts in enumerate(groups, 1):
        log_func(f"--- [{gi}/{len(groups)}] Extension group: {exts[0]}-{exts[-1]} ---")
        for i, ext in enumerate(exts):
            is_manager = (i == 0)
            privilege = "manager" if is_manager else "limited"
            acl_group_id = managers_acl_id if is_manager else users_acl_id

            # ============ GET #1: individual ACL user detail ============
            log_func(f"GET details for extension: {ext}...")
            user_data = None
            try:
                detail_resp = rest_client.get(f"RESTful/index.php/get/configuration/acluser/{ext}")
                if detail_resp.status_code == 200:
                    user_data = detail_resp.json()
                else:
                    log_func(f"  GET failed for {ext}: HTTP {detail_resp.status_code}")
                    continue
            except Exception as e:
                log_func(f"  GET error for {ext}: {e}")
                continue

            acl_user_id = user_data.get("id", "") or user_data.get("ID", "")
            username = user_data.get("username", "") or ext
            firstname = user_data.get("firstname", "")
            lastname = user_data.get("lastname", "")
            company = user_data.get("company", "")
            phone = user_data.get("phone_number", "") or user_data.get("phone", "") or username
            email = user_data.get("email", "")
            department = user_data.get("department", "")

            if not acl_user_id:
                log_func(f"  No ACL user id found for {ext}, skipping.")
                continue

            # ============ Build features array ============
            # Every ACL user — Manager and User alike — gets the extension feature plus the
            # four manager_allow capabilities. Only ``privileges`` / ``aclgroup`` still differ.
            features_arr = [{"feature": "extension", "data": ext}]
            for f in MANAGER_FEATURES:
                features_arr.append({"feature": "manager_allow", "data": f})

            # ============ POST /put/.../acluser/{id} ============
            form_data = {
                "action": "updateACLUser",
                "id": str(acl_user_id),
                "username": username,
                "password": "",
                "password2": "",
                "group": str(customer_id),
                "aclgroup": str(acl_group_id),
                "privileges": privilege,
                "features": json.dumps(features_arr),
                "monitor": json.dumps([customer_id]),
                "include_monitor_group": json.dumps([customer_id]),
                "empolyee_id": "",
                "firstname": firstname,
                "lastname": lastname,
                "firstname_p": "",
                "lastname_p": "",
                "othername": "",
                "nametitle": "",
                "company": company,
                "department": department,
                "jobTitle": "",
                "phone_number": phone,
                "mobile_number": "",
                "other_number": "",
                "sms_number1": "",
                "sms_number2": "",
                "fax": "",
                "email": email,
                "location": "",
            }

            log_func(f"  {'Manager' if is_manager else 'User'}: Updating ACL user {username} (id={acl_user_id}, aclgroup={acl_group_id})...")
            try:
                update_resp = rest_client.post_form(
                    f"RESTful/index.php/put/configuration/acluser/{acl_user_id}", form_data)
                try:
                    resp_json = update_resp.json()
                    log_func(f"  Response ({update_resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
                    api_ok = resp_json.get("success", False)
                except Exception:
                    log_func(f"  Response ({update_resp.status_code}): {update_resp.text[:500]}")
                    api_ok = False
                if update_resp.status_code == 200 and api_ok:
                    log_func(f"  ACL user '{username}' updated as {'Manager' if is_manager else 'User'}")
                    success_count += 1
                else:
                    log_func(f"  ACL user '{username}' update failed")
            except Exception as e:
                log_func(f"  REST API error for '{username}': {e}")

    log_func(f"Updated {success_count}/{total} ACL users")
    return success_count == total