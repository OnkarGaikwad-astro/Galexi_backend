import os
import requests
from flask import Flask, request, jsonify
import pytz
from datetime import datetime

app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

ist = pytz.timezone("Asia/Kolkata")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

MESSAGES_REST_URL = f"{SUPABASE_URL}/rest/v1/messages"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

def find_existing_chat(sender, receiver):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(and(sender_id.eq.{sender},receiver_id.eq.{receiver}),"
        f"and(sender_id.eq.{receiver},receiver_id.eq.{sender}))"
        f"&select=id"
    )

    res = requests.get(url, headers=HEADERS).json()

    if len(res) > 0:
        return res[0]["id"]  
    return None  


@app.route("/")
def home():
    return {"Greet": "Hello Aurex"}

@app.route("/add_message", methods=["POST"])
def add_message():
    body = request.json or {}

    sender = body.get("sender_id")
    receiver = body.get("receiver_id")
    text = body.get("msg")

    if not sender or not receiver or not text:
        return {"error": "sender_id, receiver_id, msg required"}, 400

    existing_shared_id = find_existing_chat(sender, receiver)

    if existing_shared_id:
        shared_id = existing_shared_id
    else:
        now = datetime.now(ist)
        shared_id = now.strftime("%Y%m%d%H%M%S")   

    count_url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&select=conversation_id"
    previous_msgs = requests.get(count_url, headers=HEADERS).json()
    next_convo_id = len(previous_msgs) + 1

    timestamp = datetime.now(ist).strftime("%Y-%m-%dT%H:%M:%S")

    payload = {
        "id": shared_id,
        "conversation_id": next_convo_id,
        "sender_id": sender,
        "receiver_id": receiver,
        "msg": text,
        "timestamp": timestamp
    }

    res = requests.post(MESSAGES_REST_URL, json=payload, headers=HEADERS)

    return jsonify({
        "status": "message added",
        "shared_id": shared_id,
        "conversation_id": next_convo_id
    }), res.status_code


@app.route("/messages/<shared_id>")
def get_messages(shared_id):
    url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&order=conversation_id.asc"
    res = requests.get(url, headers=HEADERS)
    rows = res.json()

    final = {
        "id": shared_id,
        "messages": rows
    }

    return jsonify(final), 200

@app.route("/message/<shared_id>/<convo_id>")
def get_message(shared_id, convo_id):
    url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&conversation_id=eq.{convo_id}"
    res = requests.get(url, headers=HEADERS)
    rows = res.json()

    if not rows:
        return {"error": "Message not found"}, 404
    return jsonify(rows[0]), 200

@app.route("/delete_message/<shared_id>/<convo_id>", methods=["DELETE"])
def delete_message(shared_id, convo_id):
    convo_id = int(convo_id)

    delete_url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&conversation_id=eq.{convo_id}"
    requests.delete(delete_url, headers=HEADERS)

    url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&order=conversation_id.asc"
    remaining = requests.get(url, headers=HEADERS).json()

    new_number = 1
    for msg in remaining:
        pk = msg["pk"]
        patch_url = f"{MESSAGES_REST_URL}?pk=eq.{pk}"
        requests.patch(
            patch_url,
            json={"conversation_id": new_number},
            headers=HEADERS
        )
        new_number += 1
    return {"status": "deleted and renumbered"}, 200

@app.route("/delete_chat/<shared_id>", methods=["DELETE"])
def delete_chat(shared_id):
    delete_url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}"
    requests.delete(delete_url, headers=HEADERS)
    return {"status": f"All messages of chat {shared_id} deleted"}, 200

@app.route("/all_chats")
def all_chats():
    url = f"{MESSAGES_REST_URL}?order=id.asc,conversation_id.asc"
    res = requests.get(url, headers=HEADERS)
    rows = res.json()

    chat_map = {}
    for msg in rows:
        chat_id = msg["id"]

        if chat_id not in chat_map:
            chat_map[chat_id] = {
                "id": chat_id,
                "messages": []
            }

        chat_map[chat_id]["messages"].append({
            "conversation_id": msg["conversation_id"],
            "sender_id": msg["sender_id"],
            "receiver_id": msg["receiver_id"],
            "msg": msg["msg"],
            "timestamp": msg["timestamp"]
        })

    final_output = list(chat_map.values())
    return jsonify(final_output), 200

@app.route("/chat/<sender>/<receiver>")
def chat_between_two(sender, receiver):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(and(sender_id.eq.{sender},receiver_id.eq.{receiver}),"
        f"and(sender_id.eq.{receiver},receiver_id.eq.{sender}))"
        f"&order=conversation_id.asc"
    )

    res = requests.get(url, headers=HEADERS)
    rows = res.json()

    if not rows:
        return {"error": "No chat found between users"}, 404

    shared_id = rows[0]["id"]

    return jsonify({
        "shared_id": shared_id,
        "messages": rows
    }), 200

@app.route("/user_chats/<user_id>")
def chats_for_user(user_id):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(sender_id.eq.{user_id},receiver_id.eq.{user_id})"
        f"&order=id.asc,conversation_id.asc"
    )

    res = requests.get(url, headers=HEADERS).json()

    if not res:
        return {"error": "No chats found"}, 404

    chat_map = {}

    for msg in res:
        shared_id = msg["id"]

        if shared_id not in chat_map:
            chat_map[shared_id] = {
                "id": shared_id,
                "messages": []
            }

        chat_map[shared_id]["messages"].append({
            "conversation_id": msg["conversation_id"],
            "sender_id": msg["sender_id"],
            "receiver_id": msg["receiver_id"],
            "msg": msg["msg"],
            "timestamp": msg["timestamp"]
        })

    final_output = list(chat_map.values())

    return jsonify(final_output), 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    print("🔥 WEBHOOK TRIGGERED")
    print("Method:", request.method)
    if request.method == "POST":
        print("Payload:", request.json)
    return {"Working": "Onkar"}, 200

if __name__ == "__main__":
    app.run(debug=True)
