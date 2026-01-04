import os
import asyncio
import random
import threading
import re
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify
from telethon import TelegramClient, events, errors, functions, types
from telethon.sessions import StringSession

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID", 35068955))
API_HASH = os.getenv("API_HASH", "55516255d54a323197d13303d2bcc3da")
SESSION_STRING = os.getenv("SESSION_STRING")

GROUP_TARGET = -1003621946413
MY_NAME = "aaronzzw"
BOT_USERNAME = "FkerKeyRPSBot"

# ================= STATE =================
last_bot_reply = "System Online."
bot_logs = ["Listener Active. Reading all chat..."]

total_grows_today = 0
total_grows_yesterday = 0
waits_today = 0
waits_yesterday = 0
coins_today = 0
coins_yesterday = 0
coins_lifetime = 0
MyAutoTimer = 30

is_muted = False
is_running = False
next_run_time = None
force_trigger = False
current_day = datetime.now(timezone(timedelta(hours=8))).day

# ================= DEBUG/STATE MACHINE =================
STATE = "IDLE"
grow_sent_at = None
retry_used = False
MAX_REPLY_WAIT = 25
cooldown_history = []
learned_cooldown = MyAutoTimer
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
            .debug { background: #111; padding: 8px; border-radius: 8px; font-size: 0.65rem; border-left: 4px solid #fbbf24; margin: 8px 0; color: #facc15; white-space: pre-wrap; }
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
                <div class="stat-box"><span class="label">Wait Today</span><span id="wt" class="stat-val" style="color:#fbbf24">0</span></div>
                <div class="stat-box"><span class="label">Wait Yesterday</span><span id="wy" class="stat-val">0</span></div>
            </div>
            <div class="label">Latest Bot Response</div>
            <div class="reply" id="reply">...</div>
            <div class="label">Debug Info</div>
            <div class="debug" id="debug">...</div>
            <div class="log-box" id="logs"></div>
        </div>
        <script>
            async function update() {
                try {
                    const res = await fetch('/api/data');
                    const d = await res.json();
                    document.getElementById('timer').innerText = d.timer;
                    document.getElementById('wt').innerText = d.wt;
                    document.getElementById('wy').innerText = d.wy;
                    document.getElementById('pt').innerText = '+' + d.pt;
                    document.getElementById('py').innerText = '+' + d.py;
                    document.getElementById('pl').innerText = d.pl.toLocaleString();
                    document.getElementById('reply').innerText = d.reply;
                    document.getElementById('status').innerText = d.status;
                    document.getElementById('status').style.color = d.color;
                    document.getElementById('logs').innerHTML = d.logs.map(l => `<div>${l}</div>`).join('');
                    document.getElementById('debug').innerText = 
                        "State: " + d.debug.state + "\\n" +
                        "Retry Used: " + d.debug.retry_used + "\\n" +
                        "Shadow-ban Warning: " + d.debug.shadow_ban_warning + "\\n" +
                        "Learned Cooldown: " + d.debug.learned_cd + "\\n" +
                        "No Reply Streak: " + d.debug.no_reply_streak;
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
        "timer": t_str, "gt": total_grows_today, "gy": total_grows_yesterday,
        "pt": coins_today, "py": coins_yesterday, "pl": coins_lifetime,
        "wt": waits_today, "wy": waits_yesterday,
        "reply": last_bot_reply.replace("@", ""), "status": s, "color": c, "logs": bot_logs,
        "debug": {"state": STATE, "retry_used": retry_used, "shadow_ban_warning": shadow_ban_flag, "learned_cd": learned_cooldown, "no_reply_streak": no_reply_streak}
    })

@app.route('/start')
def start_bot(): 
    global is_running, force_trigger
    is_running = True
    force_trigger = True
    add_log("▶ RESUME")
    return "OK"

@app.route('/stop')
def stop_bot(): 
    global is_running
    is_running = False
    add_log("■ STOP")
    return "OK"

@app.route('/restart')
def restart_bot(): 
    global is_running, force_trigger
    is_running = True
    force_trigger = True
    add_log("🔄 FORCE")
    return "OK"

@app.route('/clear_logs')
def clear_logs(): 
    global bot_logs
    bot_logs = ["Logs cleared."]
    return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def main_logic(client):
    global last_bot_reply, total_grows_today, total_grows_yesterday, coins_today, coins_yesterday, coins_lifetime
    global waits_today, waits_yesterday, is_running, force_trigger, next_run_time, current_day
    global retry_used, grow_sent_at, STATE, awaiting_bot_reply, no_reply_streak, shadow_ban_flag, learned_cooldown, is_muted

    @client.on(events.NewMessage(chats=GROUP_TARGET))
    async def handler(event):
        global last_bot_reply, coins_today, coins_lifetime, total_grows_today, waits_today
        global next_run_time, awaiting_bot_reply, retry_used, grow_sent_at, STATE, no_reply_streak, shadow_ban_flag, learned_cooldown

        try: 
            await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        except Exception as e:
            add_log(f"⚠️ Auto Seen Not Activated")

        sender = await event.get_sender()
        bot_target = BOT_USERNAME.replace("@", "").lower()
        
        if sender and sender.username and sender.username.lower() == bot_target:
            msg = event.text or ""
            if MY_NAME.lower() in msg.lower().replace("@", ""):
                last_bot_reply = msg
                awaiting_bot_reply = False
                retry_used = False
                grow_sent_at = None
                STATE = "COOLDOWN"
                no_reply_streak = 0

                if "please wait" in msg.lower():
                    waits_today += 1
                    wait_m = re.search(r'(\d+)m', msg)
                    wait_s = re.search(r'(\d+)s', msg)
                    total_wait = 0
                    if wait_m: total_wait += int(wait_m.group(1))*60
                    if wait_s: total_wait += int(wait_s.group(1))
                    
                    next_run_time = get_ph_time() + timedelta(seconds=total_wait + 5)
                    add_log(f"🕒 Wait detected: {total_wait}s")
                    return

                now_match = re.search(r'Now:\s*([\d,]+)', msg)
                if now_match: coins_lifetime = int(now_match.group(1).replace(',', ''))
                
                gain_match = re.search(r'Change:\s*\+?(-?\d+)', msg)
                if "GROW SUCCESS" in msg.upper() or gain_match:
                    total_grows_today += 1
                    if gain_match: coins_today += int(gain_match.group(1))
                    next_run_time = get_ph_time() + timedelta(hours=0, seconds=MyAutoTimer)
                    add_log(f"✅ Success! Next grow in {MyAutoTimer}s.")

    add_log("Permanent Listener Connected. Reading all chat.")
    target_group = await client.get_entity(GROUP_TARGET)
    
    while True:
        ph_now = get_ph_time()
        if ph_now.day != current_day:
            # Send 5% gift command before resetting
            if coins_today > 0:
                gift_amount = int(coins_today * 0.05)
                if gift_amount > 0:
                    try:
                        await client.send_message(GROUP_TARGET, f"/gift @Hey_Knee {gift_amount}")
                        add_log(f"🎁 Daily Gift Sent: {gift_amount} coins")
                    except Exception as e:
                        add_log(f"⚠️ Gift Error: {str(e)[:20]}")

            total_grows_yesterday, waits_yesterday, coins_yesterday = total_grows_today, waits_today, coins_today
            total_grows_today, waits_today, coins_today = 0, 0, 0
            current_day = ph_now.day

        if is_running:
            if next_run_time and ph_now < next_run_time and not force_trigger:
                STATE = "WAIT_TIMER"
                await asyncio.sleep(1)
                continue

            if awaiting_bot_reply and grow_sent_at:
                elapsed = (ph_now - grow_sent_at).total_seconds()
                if elapsed > MAX_REPLY_WAIT and not retry_used:
                    retry_used = True
                    awaiting_bot_reply = False
                    force_trigger = True
                    no_reply_streak += 1
                    add_log("🔁 No reply → retry")
                elif elapsed > MAX_REPLY_WAIT*2:
                    no_reply_streak += 1
                    awaiting_bot_reply = False

            if no_reply_streak >= 3:
                shadow_ban_flag = True
                extra_delay = random.randint(300,900)
                next_run_time = get_ph_time() + timedelta(seconds=extra_delay)
                add_log(f"🛡️ Warning (+{extra_delay}s)")
                no_reply_streak = 0

            try:
                STATE = "SENDING"
                async with client.action(target_group, 'typing'):
                    await asyncio.sleep(random.uniform(2,4))
                    await client.send_message(target_group, "/grow")
                    add_log("📤 Sent /grow")
                    awaiting_bot_reply = True
                    grow_sent_at = get_ph_time()
                    force_trigger = False
                    next_run_time = get_ph_time() + timedelta(hours=0, seconds=MyAutoTimer) 
                    STATE = "WAIT_REPLY"
                    if is_muted: is_muted = False
            except errors.ChatWriteForbiddenError:
                is_muted = True
                next_run_time = get_ph_time() + timedelta(seconds=60)
                add_log("🚫 Muted → 60s")
            except Exception as e:
                next_run_time = get_ph_time() + timedelta(seconds=30)
                add_log(f"⚠️ Error: {str(e)[:20]}")
        else:
            await asyncio.sleep(1)

async def stay_active_loop(client):
    while True:
        if is_running:
            try:
                wait_time = random.randint(180, 260)
                await asyncio.sleep(wait_time)

                messages = await client.get_messages(GROUP_TARGET, limit=5)
                if not messages:
                    continue

                if random.random() < 0.8:
                    target_msg = random.choice(messages)
                    await client(functions.messages.SendReactionRequest(
                        peer=GROUP_TARGET,
                        msg_id=target_msg.id,
                        reaction=[types.ReactionEmoji(emoticon=random.choice(['👍', '🔥', '❤️', '🤩']))]
                    ))
                    add_log("💓 Activity: Reacted to a message")
                else:
                    fillers = ["lol", "damn", "nice", "gg", "wow"]
                    async with client.action(GROUP_TARGET, 'typing'):
                        await asyncio.sleep(random.uniform(2, 5))
                        await client.send_message(GROUP_TARGET, random.choice(fillers))
                    add_log("💓 Activity: Sent filler chat")

            except Exception as e:
                add_log(f"⚠️ Activity Error: {str(e)[:20]}")
        else:
            await asyncio.sleep(5)

async def start_all():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    await asyncio.gather(
        main_logic(client), 
        stay_active_loop(client)
    )

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(start_all())
