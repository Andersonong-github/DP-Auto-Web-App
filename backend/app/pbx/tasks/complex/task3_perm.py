import json

def run_perm_task(log_func, shared_data):
    log_func(">>> Start Execute Task 3: Permission Group (REST API) <<<")

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

    base_name = shared_data.get("perm_group_prefix", "").strip()
    if not base_name:
        base_name = shared_data.get("context_prefix", "").strip()
    if not base_name:
        base_name = shared_data.get("group_name", "").strip()
    if not base_name:
        log_func("❌ No perm_group_prefix or context_prefix provided.")
        return False

    prefix = base_name[:-1] if base_name.endswith("_") else base_name

    ctx_prefix = shared_data.get("context_prefix", "").strip()
    if not ctx_prefix:
        ctx_prefix = shared_data.get("group_name", "").strip()
    ctx_base = ctx_prefix[:-1] if ctx_prefix.endswith("_") else ctx_prefix

    default_classes = [
        {"title": f"{prefix}_Class_1", "ctx": [f"{ctx_base}_Internal"]},
        {"title": f"{prefix}_Class_2", "ctx": [f"{ctx_base}_Internal", f"{ctx_base}_Fixed"]},
        {"title": f"{prefix}_Class_3", "ctx": [f"{ctx_base}_Internal", f"{ctx_base}_Fixed", f"{ctx_base}_Mobile"]},
        {"title": f"{prefix}_Class_4", "ctx": [f"{ctx_base}_Internal", f"{ctx_base}_Fixed", f"{ctx_base}_Mobile", f"{ctx_base}_IDD"]},
    ]

    # Parse custom payload: list = full class list override, dict = extra fields
    custom_classes = None
    extra_fields = {}
    _raw = shared_data.get("custom_api_payloads", {}).get("Permission Group (Auto suffix _Class_1 to _Class_4)", "")
    if _raw:
        try:
            _p = json.loads(_raw)
            if isinstance(_p, list):
                custom_classes = _p
                log_func(f"📄 Using custom class list ({len(custom_classes)} items)")
            elif isinstance(_p, dict):
                extra_fields = _p
                log_func("📄 Merging extra fields into all permission groups")
        except Exception as e:
            log_func(f"⚠️ Custom payload parse error: {e}")

    # Build the full context names from the selected context suffixes (if any)
    default_contexts = ["_Internal", "_Fixed", "_Mobile", "_IDD"]
    ctx_suffixes = [str(s).strip() for s in (shared_data.get("context_suffixes") or list(default_contexts))]

    def full_ctx(sfx):
        sfx = str(sfx).strip()
        if sfx.startswith(ctx_base):
            return sfx
        if sfx.startswith("_"):
            return f"{ctx_base}{sfx}"
        return f"{ctx_base}_{sfx}"

    if custom_classes:
        classes = custom_classes
    else:
        pg_spec = shared_data.get("pg_spec")
        if pg_spec and pg_spec.get("classes"):
            custom_ctx = next((s for s in ctx_suffixes if s not in default_contexts), None)
            fixed_std = [s for s in ("_Fixed", "_Mobile", "_IDD") if s in ctx_suffixes]
            key_front = {
                "c_i": ["Custom", "_Internal"],
                "i_c": ["_Internal", "Custom"],
                "c": ["Custom"],
                "i": ["_Internal"],
            }
            server_data = shared_data.get("pg_server_data")
            # "Load contexts" returns an empty payload when the Group does not exist yet
            # (e.g. a pipeline that creates the Group in the same run). Treat that as
            # "no server data" so the suffix fallback still produces <prefix>_Internal
            # instead of an empty contextInclude_value.
            if isinstance(server_data, dict) and not (
                server_data.get("all")
                or server_data.get("internal_ctx")
                or server_data.get("internalCtx")
                or server_data.get("custom_ctx")
                or server_data.get("customCtx")
            ):
                server_data = None
            classes = []
            for item in pg_spec["classes"]:
                if not item.get("enabled"):
                    continue
                source_class = int(item.get("source_class", item.get("class", 1)))
                class_num = int(item.get("class", source_class))
                key = str(item.get("key", "c_i"))
                title = f"{prefix}_Class_{class_num}"
                # Hand-picked contexts win: they are exact context names in tick order.
                picked = [str(c).strip() for c in (item.get("ctx") or []) if str(c).strip()]
                if picked:
                    classes.append({"title": title, "ctx": picked})
                    log_func(f"📋 {title}: using {len(picked)} hand-picked context(s): {picked}")
                    continue
                if server_data:
                    # The web API returns camelCase keys (customCtx/internalCtx), while the
                    # desktop build passed snake_case through shared_data; accept both.
                    custom_full = server_data.get("custom_ctx") or server_data.get("customCtx")
                    internal_full = server_data.get("internal_ctx") or server_data.get("internalCtx")
                    srv_fixed = server_data.get("fixed") or []
                    # Everything that really exists for this Group: used to fill a Class when
                    # the combo's own suffix is missing (e.g. Task 2 never created _Internal).
                    srv_all = (
                        server_data.get("groupAll")
                        or server_data.get("all")
                        or ([internal_full] if internal_full else [])
                        + list(srv_fixed)
                        + ([custom_full] if custom_full else [])
                    )
                    include = []
                    for name in key_front.get(key, ["_Internal"]):
                        if name == "Custom":
                            if custom_full:
                                include.append(custom_full)
                        elif name == "_Internal":
                            if internal_full:
                                include.append(internal_full)
                    include += srv_fixed[:source_class - 1]
                    if not include and srv_all:
                        # The Class asked only for contexts that do not exist on this server.
                        # Keep the Class usable by pointing it at a context that does exist
                        # rather than POSTing an empty contextInclude_value.
                        include.append(str(srv_all[0]))
                        log_func(
                            f"⚠️ {title}: its combo needs a context that does not exist on the server "
                            f"({', '.join(key_front.get(key, ['_Internal']))}); "
                            f"falling back to existing context '{include[0]}'."
                        )
                    classes.append({"title": title, "ctx": include})
                    continue
                front = list(key_front.get(key, ["_Internal"]))
                needs_custom = "Custom" in front
                if needs_custom and not custom_ctx:
                    log_func(f"⚠️ {title}: option uses Custom but no Custom context created — set one via the Context task Custom field.")
                include = []
                for name in front:
                    if name == "Custom":
                        if custom_ctx:
                            include.append(full_ctx(custom_ctx))
                    else:
                        if name in ctx_suffixes:
                            include.append(full_ctx(name))
                for s in fixed_std[:source_class - 1]:
                    include.append(full_ctx(s))
                if not include:
                    # Same guard as the server-data branch: never POST an empty context list.
                    fallback = full_ctx("_Internal")
                    include.append(fallback)
                    log_func(
                        f"⚠️ {title}: none of its contexts are being created; "
                        f"falling back to '{fallback}'."
                    )
                classes.append({"title": title, "ctx": include})
            if not classes:
                log_func("❌ No permission group classes selected.")
                return False
            log_func(f"📋 Using selected permission group classes: {[c['title'] for c in classes]}")
        else:
            classes = default_classes

    # "Add context in front of every Class": one lead context forced to position 1.
    # Applied here so it covers every branch above (hand-picked, server data, suffix
    # fallback and the default class list) and so it can never appear twice.
    pg_lead = str(shared_data.get("pg_lead") or "").strip()
    if not pg_lead:
        pg_lead = str((shared_data.get("pg_spec") or {}).get("lead") or "").strip()
    if pg_lead:
        if not custom_classes:
            for cls in classes:
                ctx_list = [str(c).strip() for c in (cls.get("ctx") or []) if str(c).strip()]
                cls["ctx"] = [pg_lead] + [c for c in ctx_list if c != pg_lead]
            log_func(f"📌 Lead context '{pg_lead}' placed first in every Class")
        else:
            for cls in classes:
                ctx_vals = cls.get("contextInclude_value", cls.get("ctx", ""))
                if isinstance(ctx_vals, list):
                    ctx_list = [str(c).strip() for c in ctx_vals if str(c).strip()]
                else:
                    ctx_list = [c.strip() for c in str(ctx_vals).split(",") if c.strip()]
                ctx_list = [pg_lead] + [c for c in ctx_list if c != pg_lead]
                cls["contextInclude_value"] = ",".join(ctx_list)
                cls["ctx"] = ctx_list
            log_func(f"📌 Lead context '{pg_lead}' placed first in every custom Class")

    success_count = 0

    for cls in classes:
        if custom_classes:
            title = cls.get("contextTitle", cls.get("title", ""))
            ctx_vals = cls.get("contextInclude_value", cls.get("ctx", ""))
            if isinstance(ctx_vals, list):
                ctx_value = ",".join(ctx_vals)
            else:
                ctx_value = str(ctx_vals)
        else:
            title = cls["title"]
            ctx_value = ",".join(cls["ctx"])

        payload = {
            "contextTitle": title,
            "group": customer_id,
            "contextDesc": "",
            "contextInclude_value": ctx_value
        }
        if extra_fields:
            payload.update(extra_fields)

        log_func(f"--- Creating Permission Group: {title} ---")
        log_func(f"   Include Contexts: {ctx_value}")
        try:
            resp = rest_client.post(
                "RESTful/index.php/v1/post/numberingplan/permissiongroup",
                payload
            )
            try:
                resp_json = resp.json()
                log_func(f"📡 Response ({resp.status_code}): {json.dumps(resp_json, indent=2, ensure_ascii=False)}")
            except Exception:
                log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
            if resp.status_code == 200:
                log_func(f"✅ {title} created successfully")
                success_count += 1
            else:
                log_func(f"❌ {title} failed")
        except Exception as e:
            log_func(f"❌ {title} error: {e}")

    log_func(f"✅ Task 3 complete: {success_count}/{len(classes)} permission groups created")
    return success_count == len(classes)
