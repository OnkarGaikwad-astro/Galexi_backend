import json
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





###### save user with user info #####

@app.route("/save_user", methods=["POST"])
def save_user():
    body = request.json or {}
    required = ["user_id", "name", "fcm_token"]
    if any(field not in body or body.get(field) == "" for field in required):
        return {"error": "user_id, name and fcm_token required"}, 400
    url = f"{SUPABASE_URL}/rest/v1/users"
    payload = {
        "user_id": body["user_id"],
        "name": body["name"],
        "fcm_token": body["fcm_token"],
        "bio": body.get("bio", ""),  
        "profile_pic": body.get("profile_pic", ""), 
        "last_seen":  datetime.now(ist).isoformat(), 
    }
    res = requests.post(
        url,
        json=payload,
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates"}
    )
    if res.status_code in (200, 201):
        return {"status": "saved"}, 200
    else:
        return {"error": "failed", "details": res.text}, 400







#####   add message with notification sending #####

NOTIFICATION_SERVER_URL = "https://us-central1-galexi-eebbe.cloudfunctions.net/sendFcmNotification"   
def send_notification_to_server(fcm_token, title, body):
    try:
        data = {
            "token": fcm_token,
            "title": title,
            "body": body
        }
        res = requests.post(NOTIFICATION_SERVER_URL, json=data)
        print("Notification Server Response:", res.text)
        return res.status_code
    except Exception as e:
        print("Error sending notification:", e)
        return None


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
    receiver_token = fetch_user_token(receiver)
    if receiver_token:
        send_notification_to_server(
            receiver_token,
            title=f"New message from {sender}",
            body=text
        )
    else:
        print("⚠️ No FCM token stored for this user:", receiver)
    return jsonify({
        "status": "message added",
        "shared_id": shared_id,
        "conversation_id": next_convo_id
    }), res.status_code




def fetch_user_token(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=fcm_token"
    res = requests.get(url, headers=HEADERS).json()
    if len(res) > 0:
        return res[0]["fcm_token"]
    return None



######  delete single message ######

@app.route("/delete_message/<sender>/<receiver>/<convo_id>", methods=["DELETE"])
def delete_one(sender, receiver, convo_id):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?and(sender_id.eq.{sender},receiver_id.eq.{receiver},conversation_id.eq.{convo_id})"
    )
    res = requests.delete(url, headers=HEADERS)
    if res.status_code == 204:
        return {"status": "Message deleted"}, 200
    else:
        return {"error": "Failed", "details": res.text}, 400


######  delete whole chat ######

@app.route("/delete_chat/<sender>/<receiver>", methods=["DELETE"])
def delete_by_users(sender, receiver):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(and(sender_id.eq.{sender},receiver_id.eq.{receiver}),"
        f"and(sender_id.eq.{receiver},receiver_id.eq.{sender}))"
    )
    res = requests.delete(url, headers=HEADERS)
    if res.status_code == 204:
        return {"status": "All messages deleted between users"}, 200
    else:
        return {"error": "Failed", "details": res.text}, 400


##### get chat #####

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
    message_count = len(rows)
    cleaned = []
    for msg in rows:
        cleaned.append({
            "msg": msg["msg"],
            "timestamp": msg["timestamp"],
            "sender_id":msg["sender_id"],
            "user_sent": "yes" if msg["sender_id"] == sender else "no"
        })
    return jsonify({
        "shared_id": shared_id,
        "message_count": message_count,
        "messages": cleaned
    }), 200


##### get user contact list #####

@app.route("/user_contacts/<user_id>")
def chats_for_user(user_id):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(sender_id.eq.{user_id},receiver_id.eq.{user_id})"
        f"&order=id.asc"
        f"&select=id,sender_id,receiver_id"
    )
    rows = requests.get(url, headers=HEADERS).json()
    if not rows:
        return {"error": "No chats found"}, 404
    chat_map = {}
    for msg in rows:
        shared_id = msg["id"]
        sender = msg["sender_id"]
        receiver = msg["receiver_id"]

        if shared_id not in chat_map:
            other_user = receiver if sender == user_id else sender
            chat_map[shared_id] = {
                "shared_id": shared_id,
                "sender_id": sender,
                "receiver_id": receiver,
                "other_user": other_user
            }
    final_output = list(chat_map.values())
    return jsonify({
        "chat_count": len(final_output),
        "chats": final_output
    }), 200


###### get user name ######

@app.route("/user_name/<user_id>")
def get_user_name(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=name"
    res = requests.get(url, headers=HEADERS).json()
    if not res:
        return {"error": "user not found"}, 404
    return {"user_id": user_id, "name": res[0]["name"]}



###### get user fcm_token ######

@app.route("/user_token/<user_id>")
def get_user_token(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=fcm_token"
    res = requests.get(url, headers=HEADERS).json()
    if not res:
        return {"error": "user not found"}, 404
    return {"user_id": user_id, "fcm_token": res[0]["fcm_token"]}



###### get ALL STORED fcm tokens ######

@app.route("/all_tokens", methods=["GET"])
def all_tokens():
    url = f"{SUPABASE_URL}/rest/v1/users?select=user_id,fcm_token"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        return {"error": "Failed to fetch tokens", "details": res.text}, 400
    data = res.json()
    return {
        "count": len(data),
        "tokens": data
    }, 200


###### get list of all saved users ######

@app.route("/all_users", methods=["GET"])
def all_users():
    url = f"{SUPABASE_URL}/rest/v1/users?select=user_id,name"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        return {"error": "Failed to fetch users", "details": res.text}, 400
    data = res.json()
    return {
        "count": len(data),
        "users": data
    }, 200


###### get user info ######

@app.route("/user_info/<user_id>")
def get_user(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=*"
    res = requests.get(url, headers=HEADERS).json()
    if not res:
        return {"error": "user not found"}, 404
    return res[0]


###### get all saved users info ######

@app.route("/all_users_info", methods=["GET"])
def all_users_info():
    url = f"{SUPABASE_URL}/rest/v1/users?select=*"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        return {
            "error": "Failed to fetch user info",
            "details": res.text
        }, 400
    users = res.json()
    return {
        "count": len(users),
        "users": users
    }, 200



####### update user last seen #####

@app.route("/update_last_seen/<user_id>", methods=["POST"])
def update_last_seen(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}"
    res = requests.patch(
        url,
        json={"last_seen": datetime.utcnow().isoformat()},
        headers=HEADERS
    )
    if res.status_code == 204:
        return {"status": "last seen updated"}
    else:
        return {"error": "failed", "details": res.text}, 400


###### get user last seen #####

@app.route("/last_seen/<user_id>", methods=["GET"])
def get_last_seen(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=last_seen"
    res = requests.get(url, headers=HEADERS).json()
    if not res:
        return {"error": "user not found"}, 404
    return {
        "user_id": user_id,
        "last_seen": res[0]["last_seen"]
    }



if __name__ == "__main__":
    app.run(debug=True)
