/**
 * catalog.js — static catalog data (optional task list, migration roadmap, parameter preview).
 *
 * Pipeline tasks themselves come from the backend /api/config tasks; only frontend-specific parts live here.
 */

/** Tasks in modules_optional/, matching the desktop “Optional Tasks” page. */
export const OPTIONAL_TASKS = [
  { key: 'group', cn: 'User Group', en: 'Group' },
  { key: 'context', cn: 'Number Context', en: 'Context' },
  { key: 'permgroup', cn: 'Permission Group', en: 'Permission Group' },
  { key: 'permgroup_tool', cn: 'Permission Group Tool', en: 'Permission Group Tool' },
  { key: 'siptrunk', cn: 'SIP Trunk', en: 'SIP Trunk' },
  { key: 'siptrunkstatus', cn: 'SIP Trunk Status', en: 'SIP Trunk Status' },
  { key: 'outboundrouting', cn: 'Outbound Routing', en: 'Outbound Routing' },
  { key: 'inboundrouting', cn: 'Inbound Routing', en: 'Inbound Routing' },
  { key: 'calleridmanipulation', cn: 'Caller ID Manipulation', en: 'Caller ID Manipulation' },
  { key: 'aclgroup', cn: 'ACL Group', en: 'ACL Group' },
  { key: 'acluser', cn: 'ACL User', en: 'ACL User' },
  { key: 'userprofile', cn: 'User Profile', en: 'User Profile' },
  { key: 'userprofile_tool', cn: 'User Profile Tool', en: 'User Profile Tool' },
  { key: 'user', cn: 'User (Extension)', en: 'User' },
  { key: 'number_create', cn: 'Number Create', en: 'Number Create' },
  { key: 'number_search', cn: 'Number Search / Delete', en: 'Number Search & Delete' },
  { key: 'numberstrip', cn: 'Number Strip', en: 'Number Strip' },
  { key: 'number_voiceprompt', cn: 'Number Voice Prompt', en: 'Number Voice Prompt' },
  { key: 'voiceprompt', cn: 'Voice Prompt', en: 'Voice Prompt' },
  { key: 'ivr', cn: 'IVR Voice Navigation', en: 'IVR' },
  { key: 'queue', cn: 'Call Queue', en: 'Queue' },
  { key: 'ringgroup', cn: 'Ring Group', en: 'Ring Group' },
  { key: 'huntgroup', cn: 'Hunt Group', en: 'Hunt Group' },
  { key: 'agentgroups', cn: 'Agent Group', en: 'Agent Group' },
  { key: 'agents', cn: 'Agent', en: 'Agent' },
  { key: 'callforward', cn: 'Call Forward', en: 'Call Forward' },
  { key: 'callpickup', cn: 'Call Pickup', en: 'Call Pickup' },
  { key: 'namesplit', cn: 'Name Split Tool', en: 'Name Split' },
];

/** Parameter preview for Standard / Complex mode (maps to standard_parameter.json). */
export const PARAMETER_PREVIEW = [
  { key: 'group_name', cn: 'Group Name', sample: 'ABC' },
  { key: 'group_code', cn: 'Group Code', sample: 'ABC' },
  { key: 'unified_limit', cn: 'Unified Number Limit', sample: '10' },
  { key: 'host_ip', cn: 'SIP Trunk Host', sample: '192.168.1.0' },
  { key: 'port', cn: 'SIP Trunk Port', sample: '5060' },
  { key: 'context_prefix', cn: 'Context Prefix', sample: 'ABC' },
  { key: 'perm_group_prefix', cn: 'Permission Group Prefix', sample: 'ABC' },
  { key: 'inbound_ranges', cn: 'Inbound Number Range', sample: '60358797500 - 60358797509' },
  { key: 'user_ext', cn: 'User Extension Range', sample: '0358797500 - 0358797502' },
  { key: 'htek_model', cn: 'Htek Phone Model', sample: 'uc902g' },
];

export const ROADMAP = [
  { stage: 'Stage 0', title: 'Backend Proxy & Session Auth', detail: 'FastAPI proxy for PBX REST, HttpOnly sessions, login throttling, SSRF blocking.', status: 'done' },
  { stage: 'Stage 1', title: 'Login Page & App Shell', detail: 'uiverse login page, nav shell, dashboard, connection self-check, log console.', status: 'done' },
  { stage: 'Stage 2', title: 'Standard Pipeline', detail: '13-step task parameter form, selection and run, live SSE logs, status lights, extension record export.', status: 'done' },
  { stage: 'Stage 3', title: 'Complex Pipeline', detail: 'Context suffix / four Permission Group types / ACL / profile types and recording / ACL User roles / lists / custom payload.', status: 'done' },
  { stage: 'Stage 4', title: 'Optional Tasks Page', detail: 'Search & Delete and SIP Trunk Status are live; the remaining optional tasks are still being migrated.', status: 'next' },
  { stage: 'Stage 5', title: 'Operations', detail: 'Task history, audit logs, multi-operator accounts, backup and upgrade flows.', status: 'todo' },
];

export const ROADMAP_BADGE = {
  done: { text: 'Done', variant: 'ok' },
  next: { text: 'In Progress', variant: 'brand' },
  todo: { text: 'Not Scheduled', variant: '' },
};
