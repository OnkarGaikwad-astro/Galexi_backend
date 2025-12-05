import os
import requests
from flask import Flask, request, jsonify
import pytz
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, messaging

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


##### Firebase Notification #####

service_account_info = {
  "type": "service_account",
  "project_id": "galexi-eebbe",
  "private_key_id": "27f1fcc01ef8c7c78864a57f940848b2fb78c389",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC+1mo7qZ80gyWB\nz/iztfTgW9YFXQRrOnFGpfGththwZju6nVbLyUNnGH5jjmzKeDLRutsWd3ZBVMow\npqtH3eIAen8IsypZdSITOMshJNk6Fsh+ThcY3YO3yIZ79lKC/e8raTOw6eIuyucZ\nK/w1sgTZVVwuLJq5uUcu5GnIY8iL3dbXVjaDAJNd0TyOLAQY+ebFtoVLBFsUltHZ\nSb2bKJRc1XxyFXQjGlNQ6FArvK1i6TMWCVA8PmyIkbOh2C9W+Bb2sLvklQmS7INf\nE20IXarzsRf21tygJ0Q2QmHzmden4O7kgWKfXDGGxFNBXrb/dD10ohESk0ptz8C9\ndEBUjaP/AgMBAAECggEAOmmvAqwcyxoJdP6PhZKAbdwuWl3qaFfvLEzG+PJ5dY4V\nYj2ev6nPM9NPfHGv4xl/lKq5PNs8Gys06Edbzheggbz8/VC5+b/cuj18D50T0LAA\nloiYkUfcdXivkWoIP4gymPsOk2xDi0cYDaBlBpqC2XNDT+7fPVH08+l+Z5QDYqvw\ne1k+qLfvHa4r2kwicQuscwQPh8cYoqPTTJhWDw7ULD5CjvHdb4qSk7LPJ5mzc5Kt\nt/bJI2rSYe9Z6QyNIDxMjXWIqKf5/EN9TPsFuM/PZPsKiHs+9XnONAoLceBsKVNI\nNgMrnNHKOutaDPKib7yUJNsgpzUSePc9DqIy8PAF4QKBgQD1AwWOWKTuqjaXzgBE\n0+jWpMev1p4i+o3jdogzyr33ywzivjHvMJ9Cv28LyRBdnbCosQESrlJSrSsEBW25\n9/IYFZwOlQ71Rh8hpn7kA8QpvQvpuhroxizXDB/9TMWh2XylEpJyYIBIcvPu4E/6\n2WEnoyHdQCJPdtP39jsIdO2X8wKBgQDHZWtUKxcxD1Gggf74ORg91RIgMHk0C/26\nKNKN2sSD0tZY6Kpxr0B8qBHcX0sHRIEp7vRRbz5dlijRtIeUF2LxIAvEj2ARFLvn\nWw7pPlBnK2JDrtot7v/xjn1DXsCiGvgZt6bxD/rodK5HygBL6t9tZX6z63u60uww\nbjUQOJzyxQKBgQCSwX+XdsM77ZqLrSl+EIwb3VF6oovQGdHZWEtW8m59ORN70T6p\nra8HVREXtxRlbqm9MWCaJu5KdU0ZuIKz7K8G/BKgrWnrQlgtWMQSoari8UhsdDvg\nB6weFzYmC9EpE9NUMN6lQeY0/x3bjGJ7t685Bb6n/t1OSbfHg6Zyd09FPwKBgFi8\ny+0jWCjfNmaGM+BoGF+8KVrl96qwA3ULodi7mWVJOVdMBD6fzcUsTvaR+iP72re8\nvkJXjZu8reHVw9imJ8RDjLknTYuMfKtTnOk0cDfZ2NtiP3rduE3aKekHjBcYhX18\ne/EgOXumIcGVJlii6FgZKTANBn14TOCoyziy2TY5AoGALtf2CC/fnGfl1oUR9PU1\nBGXiocMQYY+vbscjC3JxXdNmfxDvq2PnjIMv0cSMb4KBuI8GKWC5gzoG9IjbliQJ\nJUlwVm7eJTxocYchB1zEwHznJWQoP5pOF1OjOYvvUJXeFqTg4bZ/ZlVmIsnGbBSh\nuboYGwDvGJ0M6LXlW9SlHdw=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@galexi-eebbe.iam.gserviceaccount.com",
  "client_id": "114173166631867812331",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40galexi-eebbe.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)

# ---------------------- ROUTE TO SEND NOTIFICATIONS ----------------------

@app.route("/send_notification", methods=["POST"])
def send_notification():
    data = request.json
    token = data.get("token")
    title = data.get("title")
    body = data.get("body")
    # Build Notification
    message = messaging.Message(
        token=token,
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        android=messaging.AndroidConfig(
            priority="high"
        )
    )
    # Send notification
    response = messaging.send(message)
    return jsonify({"status": "sent", "message_id": response})



@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    print("🔥 WEBHOOK TRIGGERED")
    print("Method:", request.method)
    if request.method == "POST":
        print("Payload:", request.json)
    return {"Working": "Onkar"}, 200

if __name__ == "__main__":
    app.run(debug=True)
