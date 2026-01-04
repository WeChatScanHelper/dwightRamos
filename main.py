import os
import asyncio
import random
import threading
import re
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID", 35068955))
API_HASH = os.getenv("API_HASH", "55516255d54a323197d13303d2bcc3da")
SESSION_STRING = os.getenv("SESSION_STRING")

GROUP_TARGET = -1003621946413
MY_NAME = "aaronzzw"
BOT_USERNAME = "FkerKeyRPSBot"

# ================= STATE =================
last_bot_reply = "System Online. Waiting for start..."
bot_logs = ["Listener Active. Reading all chat..."]

total_grows_today = 0
total_grows_yesterday = 0
waits_today = 0
waits_yesterday = 0
coins_today = 0
coins_yesterday = 0
coins_lifetime = 0

is_muted = False
is_running = False
next_run_time = None
force_trigger = False
current_day = datetime.now(timezone(timedelta(hours=8))).day

STATE = "IDLE"
grow_sent_at = None
retry_used = False
MAX_REPLY_WAIT = 25
no_reply_streak = 0
shadow_ban_flag = False
awaiting_bot_reply = False

# ================= UTILS =================
def get_ph_time():
    return datetime.now(timezone(timedelta(hours=8)))

def add_log(text):
    ts = get_ph_time().strftime("%H:%M:%S")
    bot_logs.insert(0, f"[{ts}] {text.replace('@','')}")
    if len(bot_logs) > 100: bot_logs.pop()

# ================= WEB UI =================
app = Flask(__name__)

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PH Turbo Admin</title>
        <style>
            :root { --bg: #0f172a; --card: #1e293b; --acc: #38bdf8; --text: #f8fafc; }
            body { font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 10px; display: flex; justify-content: center; }
            .card { width: 100%; max-width: 500px; background: var(--card); padding: 20px; border-radius: 24px; border: 1px solid #334155; }
            .timer { font-size: 3rem; font-weight: 900; text-align: center; margin: 5px 0; color: #fbbf24; }
            .status-badge { font-size: 0.7rem; font-weight: 800; text-align: center; margin-bottom: 10px; text-transform: uppercase; }
            .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 15px 0; }
            .stat-box { background: rgba(0,0,0,0.2); padding: 10px; border-radius: 12px; border: 1px solid #334155; }
            .stat-val { font-size: 1.1rem; font-weight: 800; display: block; }
            .label { font-size: 0.55rem; color: #94a3b8; text-transform: uppercase; font-weight: 700; }
            .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
            .btn { padding: 12px; border-radius: 10px; border: none; font-weight: 800; cursor: pointer; color: white; font-size: 0.75rem; transition: 0.2s; }
            .log-box { background: #000; height: 180px; overflow-y: auto; padding: 10px; font-family: monospace; font-size: 0.7rem; border-radius: 10px; color: #4ade80; border: 1px solid #334155; }
            .reply { background: #0f172a; padding: 10px; border-radius: 10px; font-size: 0.8rem; border-left: 4px solid var(--acc); margin: 12px 0; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="card">
            <div id="status" class="status-badge">...</div>
            <div class="timer" id="timer">--</div>
            <div class="btn-group">
                <button onclick="fetch('/start')" class="btn" style="background:#059669">▶ RESUME</button>
                <button onclick="fetch('/stop')" class="btn" style="background:#dc2626">■ STOP</button>
                <button onclick="fetch('/restart')" class="btn" style="background:#38bdf8">🔄 FORCE</button>
                <button onclick="fetch('/clear_logs')" class="btn" style="background:#64748b">🧹 CLEAR</button>
            </div>
            <div class="stats-grid">
                <div class="stat-box" style="grid-column: span 2; text-align: center; border-color: var(--acc);">
                    <span class="label" style="color: var(--acc);">Lifetime Total Coins</span>
                    <span id="pl" class="stat-val" style="font-size: 1.6rem;">0</span>
                </div>
                <div class="stat-box"><span class="label">Coins Today</span><span id="pt" class="stat-val" style="color:#4ade80">+0</span></div>
                <div class="stat-box"><span class="label">Coins Yesterday</span><span id="py" class="stat-val">+0</span></div>
            </div>
            <div class="label">Latest Bot Response</div>
            <div class="reply" id="reply">...</div>
            <div class="log-box" id="logs"></div>
        </div>
        <script>
            async function update() {
                try {
                    const res = await fetch('/api/data');
                    const d = await res.json();
                    document.getElementById('timer').innerText = d.timer;
                    document.getElementById('pt').innerText = '+' + d.pt;
                    document.getElementById('pl').innerText = d.pl.toLocaleString();
                    document.getElementById('reply').innerText = d.reply;
                    document.getElementById('status').innerText = d.status;
                    document.getElementById('status').style.color = d.color;
                    document.getElementById('logs').innerHTML = d.logs.map(l => `<div>${l}</div>`).join('');
                } catch (e) {}
            }
            setInterval(update, 1000);
        </script>
    </body>
    </html>
    """

@app.route('/api/data')
def get_data():
    ph_now = get_ph_time()
    t_str = "--"
    s, c = "🟢 ACTIVE", "#34d399"
    if is_muted: s, c, t_str = "⚠️ MUTED (1m RETRY)", "#fbbf24", "MUTE"
    elif not is_running: s, c, t_str = "🛑 STOPPED", "#f87171", "OFF"
    elif next_run_time:
        diff = int((next_run_time - ph_now).total_seconds())
        if diff > 0:
            m, s_rem = divmod(diff, 60)
            t_str = f"{m}m {s_rem}s"
        else: t_str = "READY"
    return jsonify({
        "timer": t_str, "pt": coins_today, "pl": coins_lifetime,
        "reply": last_bot_reply.replace("@", ""), "status": s, "color": c, "logs": bot_logs
    })

@app.route('/start')
def start_bot(): 
    global is_running, force_trigger; is_running = True; force_trigger = True
    add_log("▶ RESUME"); return "OK"

@app.route('/stop')
def stop_bot(): 
    global is_running; is_running = False
    add_log("■ STOP"); return "OK"

@app.route('/restart')
def restart_bot(): 
    global is_running, force_trigger; is_running = True; force_trigger = True
    add_log("🔄 FORCE"); return "OK"

@app.route('/clear_logs')
def clear_logs(): 
    global bot_logs; bot_logs = ["Logs cleared."]; return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

# ================= TELEGRAM LOGIC =================
async def main_logic():
    global last_bot_reply, total_grows_today, total_grows_yesterday, coins_today, coins_yesterday, coins_lifetime
    global waits_today, waits_yesterday, is_running, force_trigger, next_run_time, current_day
    global retry_used, grow_sent_at, STATE, awaiting_bot_reply, no_reply_streak, shadow_ban_flag, is_muted

    if not SESSION_STRING:
        add_log("❌ ERROR: SESSION_STRING missing.")
        return

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

    @client.on(events.NewMessage(chats=GROUP_TARGET))
    async def handler(event):
        global last_bot_reply, coins_today, coins_lifetime, total_grows_today, waits_today
        global next_run_time, awaiting_bot_reply, retry_used, grow_sent_at, STATE, no_reply_streak

        sender = await event.get_sender()
        bot_target = BOT_USERNAME.replace("@", "").lower()
        
        if sender and sender.username and sender.username.lower() == bot_target:
            msg = event.text or ""
            if MY_NAME.lower() in msg.lower().replace("@", ""):
                last_bot_reply = msg
                awaiting_bot_reply = False
                retry_used = False
                no_reply_streak = 0
                STATE = "COOLDOWN"

                if "please wait" in msg.lower():
                    waits_today += 1
                    wait_m = re.search(r'(\d+)m', msg)
                    wait_s = re.search(r'(\d+)s', msg)
                    total_wait = 0
                    if wait_m: total_wait += int(wait_m.group(1))*60
                    if wait_s: total_wait += int(wait_s.group(1))
                    next_run_time = get_ph_time() + timedelta(seconds=total_wait + 5)
                    add_log(f"🕒 Wait: {total_wait}s")
                
                now_match = re.search(r'Now:\s*([\d,]+)', msg)
                if now_match: coins_lifetime = int(now_match.group(1).replace(',', ''))
                
                gain_match = re.search(r'Change:\s*\+?(-?\d+)', msg)
                if "GROW SUCCESS" in msg.upper() or gain_match:
                    if gain_match: coins_today += int(gain_match.group(1))
                    next_run_time = get_ph_time() + timedelta(hours=1, seconds=10)
                    add_log("✅ Success! Next in 1hr.")

    try:
        await client.connect()
        if not await client.is_user_authorized():
            add_log("❌ SESSION INVALID")
            return
        add_log("🚀 Connected to Telegram")
    except Exception as e:
        add_log(f"❌ Conn Error: {str(e)[:20]}")
        return

    target_group = await client.get_entity(GROUP_TARGET)

    while True:
        try:
            ph_now = get_ph_time()

            if ph_now.day != current_day:
                total_grows_today, waits_today, coins_today = 0, 0, 0
                current_day = ph_now.day
                add_log("🌅 New Day Reset")

            if is_running:
                if next_run_time and ph_now < next_run_time and not force_trigger:
                    STATE = "WAITING"
                    await asyncio.sleep(1)
                    continue

                if awaiting_bot_reply and grow_sent_at:
                    if (ph_now - grow_sent_at).total_seconds() > MAX_REPLY_WAIT:
                        awaiting_bot_reply = False
                        no_reply_streak += 1
                        force_trigger = True
                        add_log("🔁 Retrying...")

                if no_reply_streak >= 3:
                    delay = random.randint(300, 600)
                    next_run_time = get_ph_time() + timedelta(seconds=delay)
                    add_log(f"🛡️ Protection: {delay}s")
                    no_reply_streak = 0
                    continue

                STATE = "SENDING"
                if not client.is_connected(): await client.connect()

                async with client.action(target_group, 'typing'):
                    await asyncio.sleep(random.uniform(2, 4))
                    await client.send_message(target_group, "/grow")
                    add_log("📤 Sent /grow")
                    
                    awaiting_bot_reply = True
                    grow_sent_at = ph_now
                    force_trigger = False
                    next_run_time = ph_now + timedelta(hours=1, seconds=10)
                    if is_muted: is_muted = False

        except errors.ChatWriteForbiddenError:
            is_muted = True
            next_run_time = get_ph_time() + timedelta(seconds=60)
            add_log("🚫 Muted (60s)")
        except (errors.RPCError, ConnectionError):
            add_log("📡 Reconnecting...")
            try: await client.disconnect(); await client.connect()
            except: pass
        except Exception as e:
            add_log(f"⚠️ Loop Error: {str(e)[:20]}")
            
        await asyncio.sleep(1)

if __name__ == "__main__":
    # Start Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Telegram
    try:
        asyncio.run(main_logic())
    except Exception as e:
        print(f"MAIN LOGIC CRASH: {e}")

    # KEEP-ALIVE: Stops Render from exiting
    while True:
        time.sleep(3600)
