import json

ROUTING_RULES = [
    ("_+60[2-9]X.",  "_Fixed"),
    ("_+601X.",      "_Mobile"),
    ("_+X.",         "_IDD"),
    ("_0[2-9]X.",    "_Fixed"),
    ("_00X.",        "_IDD"),
    ("_01X.",        "_Mobile"),
    ("_1300X.",      "_Fixed"),
    ("_1800X.",      "_Fixed"),
    ("_ZXX",         "_Fixed"),
    ("_ZXXXX",       "_Fixed"),
]

def run_outbound_task(log_func, shared_data):
    log_func(">>> Start Execute Task 5: Outbound Routing (REST API) <<<")

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
    if not group_name:
        log_func("❌ No group_name provided.")
        return False

    ctx_prefix = shared_data.get("context_prefix", "").strip()
    if not ctx_prefix:
        ctx_prefix = shared_data.get("perm_group_prefix", "").strip()
    if not ctx_prefix:
        ctx_prefix = group_name
    ctx_base = ctx_prefix[:-1] if ctx_prefix.endswith("_") else ctx_prefix

    # Fetch the contexts that actually exist for this customer, so the
    # routing rule's `context` value can be validated before posting.
    existing_contexts = None
    try:
        _ctx_search = (rest_client.search_contexts_by_group(customer_id, group_name)
                       if hasattr(rest_client, "search_contexts_by_group") else None)
        if _ctx_search:
            existing_contexts = {str(c.get("contextID") or "").strip()
                                 for c in _ctx_search if c.get("contextID")}
    except Exception:
        existing_contexts = None

    def ensure_context(number, ctx_value):
        """Resolve ctx_value to an existing context name.

        Exact match wins; otherwise an underscore-insensitive match is tried
        (e.g. 'Xxx_SetiaAlam_Fixed' -> 'Xxx_Setia_Alam_Fixed'). Returns None
        when no matching context exists. When the server list is unavailable,
        returns ctx_value unchanged.
        """
        if existing_contexts is None:
            return ctx_value
        if ctx_value in existing_contexts:
            return ctx_value
        norm = lambda s: str(s).replace("_", "").lower()
        target = norm(ctx_value)
        for cand in sorted(existing_contexts):
            if norm(cand) == target:
                log_func(f"ℹ️ {number}: matched existing context '{cand}' (from '{ctx_value}')")
                return cand
        log_func(f"⚠️ {number}: context '{ctx_value}' does NOT exist for this customer — "
                 f"run Task 2 (Context) first or check the context_prefix. Skipping this rule.")
        return None

    # Parse custom payload: list = full rule override, dict = extra fields
    custom_rules = None
    extra_fields = {}
    _raw = shared_data.get("custom_api_payloads", {}).get("Outbound Routing (10 rules)", "")
    if _raw:
        try:
            _p = json.loads(_raw)
            if isinstance(_p, list):
                custom_rules = _p
                log_func(f"📄 Using custom routing rule list ({len(custom_rules)} items)")
            elif isinstance(_p, dict):
                extra_fields = _p
                log_func("📄 Merging extra fields into all routing rules")
        except Exception as e:
            log_func(f"⚠️ Custom payload parse error: {e}")

    # Resolve the actual SIP peer ID for this customer from the server
    # (SIP Trunk stores a real peerID that may differ from group_name).
    _peer = group_name
    try:
        _trunks = (rest_client.search_siptrunks_by_peerid(group_name, customer_id, group_name)
                   if hasattr(rest_client, "search_siptrunks_by_peerid") else None)
        if _trunks:
            _peer = _trunks[0].get("peerID") or group_name
            log_func(f"📞 SIP peer resolved: '{_peer}' (from group '{group_name}')")
    except Exception:
        pass

    # Custom Routing mode (single number + context from the Complex tab)
    custom_routing_mode = bool(shared_data.get("custom_routing_mode"))

    def build_payload(number, ctx_value):
        routing_step = json.dumps([{
            "number": number,
            "context": ctx_value,
            "description": "",
            "routing_id": "",
            "step": "1",
            "peer_type": 1,
            "peer_display": _peer,
            "peerID": _peer,
            "digit_strip": "",
            "digit_prepend": "",
            "callerid_handling": 4,
            "callerid_autoresolve": 1,
            "callerid_strip": None,
            "callerid_rewrite": "",
            "country_code": "",
            "countryarea_calling_code": "",
            "routing_type": "",
            "strip_method": "0"
        }])
        pl = {
            "sippeer_value": _peer,
            "sippeergroup_value": "",
            "routing_steps": routing_step,
            "routing_type": "",
            "number": number,
            "context": ctx_value,
            "description": "",
            "peer_type": 1,
            "digit_strip": "",
            "digit_prepend": "",
            "callerid_handling": 4,
            "callerid_autoresolve": 1,
            "callerid_strip": "",
            "callerid_rewrite": ""
        }
        return pl

    success_count = 0
    total = 0

    if custom_routing_mode:
        number = (shared_data.get("custom_number") or "").strip()
        ctx_sel = (shared_data.get("custom_context") or "").strip()
        if not number:
            log_func("❌ Custom Routing requires a number in the Custom Number field.")
            return False
        if not ctx_sel or ctx_sel == "Custom":
            log_func("❌ Custom Routing requires a context selection (dropdown) or refresh it first.")
            return False
        if ctx_sel.startswith("_"):
            ctx_value = f"{ctx_base}{ctx_sel}"
        else:
            ctx_value = ctx_sel
        total = 1
        resolved_ctx = ensure_context(number, ctx_value)
        if not resolved_ctx:
            return False
        pl = build_payload(number, resolved_ctx)
        if extra_fields:
            pl.update(extra_fields)
        log_func(f"--- [1/1] Creating Custom Outbound Routing: {number} -> {ctx_value} ---")
        try:
            resp = rest_client.post_form(
                "RESTful/index.php/v1/post/numberingplan/outboundrouting",
                pl
            )
            try:
                d = resp.json()
                log_func(f"📡 Response ({resp.status_code}): {json.dumps(d, indent=2, ensure_ascii=False)}")
            except Exception:
                d = {}
                log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
            if resp.status_code == 200 and d.get("success", True):
                log_func(f"✅ [1/1] {number} created")
                success_count += 1
            else:
                log_func(f"❌ [1/1] {number} failed")
        except Exception as e:
            log_func(f"❌ [1/1] {number} error: {e}")
    elif custom_rules:
        for i, item in enumerate(custom_rules, 1):
            number = item.get("number", "")
            ctx_value = item.get("context", f"{ctx_base}_Fixed")
            resolved_ctx = ensure_context(number, ctx_value)
            if not resolved_ctx:
                continue
            pl = build_payload(number, resolved_ctx)
            for k, v in item.items():
                if k not in ("number", "context", "routing_steps"):
                    pl[k] = v
            _rs = item.get("routing_steps")
            if _rs:
                pl["routing_steps"] = _rs if isinstance(_rs, str) else json.dumps(_rs)
            log_func(f"--- [{i}/{len(custom_rules)}] Creating Outbound Routing: {number} ---")
            total = len(custom_rules)
            try:
                resp = rest_client.post_form(
                    "RESTful/index.php/v1/post/numberingplan/outboundrouting",
                    pl
                )
                try:
                    d = resp.json()
                    log_func(f"📡 Response ({resp.status_code}): {json.dumps(d, indent=2, ensure_ascii=False)}")
                except Exception:
                    d = {}
                    log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
                if resp.status_code == 200 and d.get("success", True):
                    log_func(f"✅ [{i}/{len(custom_rules)}] {number} created")
                    success_count += 1
                else:
                    log_func(f"❌ [{i}/{len(custom_rules)}] {number} failed")
            except Exception as e:
                log_func(f"❌ [{i}/{len(custom_rules)}] {number} error: {e}")
    else:
        total = len(ROUTING_RULES)
        for i, (number, ctx_suffix) in enumerate(ROUTING_RULES, 1):
            ctx_value = f"{ctx_base}{ctx_suffix}"
            resolved_ctx = ensure_context(number, ctx_value)
            if not resolved_ctx:
                continue
            pl = build_payload(number, resolved_ctx)
            if extra_fields:
                pl.update(extra_fields)
            log_func(f"--- [{i}/{total}] Creating Outbound Routing: {number} -> {ctx_suffix} ---")
            try:
                resp = rest_client.post_form(
                    "RESTful/index.php/v1/post/numberingplan/outboundrouting",
                    pl
                )
                try:
                    d = resp.json()
                    log_func(f"📡 Response ({resp.status_code}): {json.dumps(d, indent=2, ensure_ascii=False)}")
                except Exception:
                    d = {}
                    log_func(f"📡 Response ({resp.status_code}): {resp.text[:300]}")
                if resp.status_code == 200 and d.get("success", True):
                    log_func(f"✅ [{i}/{total}] {number} created")
                    success_count += 1
                else:
                    log_func(f"❌ [{i}/{total}] {number} failed")
            except Exception as e:
                log_func(f"❌ [{i}/{total}] {number} error: {e}")

    log_func(f"✅ Task 5 complete: {success_count}/{total} outbound routings created")
    return success_count == total
