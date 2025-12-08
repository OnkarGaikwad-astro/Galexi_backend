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
    if any(field not in body or not body[field] for field in required):
        return {"error": "user_id, name and fcm_token required"}, 400
    user_id = body["user_id"]
    check_url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}"
    check_res = requests.get(check_url, headers=HEADERS)
    if check_res.status_code != 200:
        return {"error": "failed checking user", "details": check_res.text}, 400
    exists = len(check_res.json()) > 0
    payload = {
        "user_id": user_id,
        "name": body["name"],
        "fcm_token": body["fcm_token"],
        "bio": body.get("bio", ""),
        "profile_pic": body.get("profile_pic", ""),
        "phone_no": body.get("phone_no", ""),
        "last_seen": datetime.now(ist).isoformat(),
    }
    if exists:
        res = requests.patch(
            check_url,
            json=payload,
            headers=HEADERS
        )

        if res.status_code in (200, 204):
            return {"status": "updated"}, 200
        return {"error": "update failed", "details": res.text}, 400
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/users",
        json=payload,
        headers=HEADERS
    )
    if res.status_code in (200, 201):
        return {"status": "inserted"}, 200
    return {"error": "insert failed", "details": res.text}, 400




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
    timestamp = datetime.now(ist).strftime("%Y-%m-%d \n %H:%M:%S")
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




###### get user all chats #######

@app.route("/all_chats/<user_id>")
def all_chats(user_id):
    contacts_url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(sender_id.eq.{user_id},receiver_id.eq.{user_id})"
        f"&select=sender_id,receiver_id"
    )
    rows = requests.get(contacts_url, headers=HEADERS).json()
    if not rows:
        return {"user_id": user_id, "contact_count": 0, "chats": []}, 200
    contacts = set()
    for chat in rows:
        other = chat["receiver_id"] if chat["sender_id"] == user_id else chat["sender_id"]
        contacts.add(other)
    all_chats_data = []
    for contact in contacts:
        chat_url = (
            f"{MESSAGES_REST_URL}"
            f"?or=(and(sender_id.eq.{user_id},receiver_id.eq.{contact}),"
            f"and(sender_id.eq.{contact},receiver_id.eq.{user_id}))"
            f"&order=conversation_id.asc"
        )
        chat_rows = requests.get(chat_url, headers=HEADERS).json()
        cleaned_messages = []
        for msg in chat_rows:
            cleaned_messages.append({
                "msg": msg["msg"],
                "timestamp": msg["timestamp"],
                "sender_id": msg["sender_id"],
                "receiver_id": msg["receiver_id"],
                "user_sent": "yes" if msg["sender_id"] == user_id else "no"
            })
        all_chats_data.append({
            "contact_id": contact,
            "message_count": len(cleaned_messages),  
            "messages": cleaned_messages
        })
    return {
        "user_id": user_id,
        "contact_count": len(all_chats_data),
        "chats": all_chats_data
    }, 200




##### get user contact list #####

@app.route("/user_contacts/<user_id>")
def user_contacts(user_id):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(sender_id.eq.{user_id},receiver_id.eq.{user_id})"
        f"&select=sender_id,receiver_id,msg,msg_seen,timestamp"
        f"&order=timestamp.desc"
    )
    rows = requests.get(url, headers=HEADERS).json()
    if not rows:
        return {"contact_count": 0, "contacts": []}, 200
    contact_map = {}
    for msg in rows:
        sender = msg["sender_id"]
        receiver = msg["receiver_id"]
        other_user = receiver if sender == user_id else sender
        if other_user not in contact_map:
            contact_map[other_user] = {
                "id": other_user,
                "last_message": msg["msg"],
                "last_message_time": msg["timestamp"],
                "last_message_sender_id": sender,
                "last_message_seen": msg["msg_seen"],
            }
    contact_ids = list(contact_map.keys())
    if not contact_ids:
        return {"contact_count": 0, "contacts": []}, 200
    ids_str = ",".join(contact_ids)
    users_url = (
        f"{SUPABASE_URL}/rest/v1/users"
        f"?user_id=in.({ids_str})"
        f"&select=user_id,name,profile_pic"
    )
    user_rows = requests.get(users_url, headers=HEADERS).json()
    final_contacts = []
    for u in user_rows:
        uid = u["user_id"]
        last = contact_map[uid]
        if last["last_message_sender_id"] == user_id:
            seen_status = "seen"
        else:
            seen_status = last["last_message_seen"]
        final_contacts.append({
            "id": uid,
            "name": u.get("name", ""),
            "profile_pic": u.get("profile_pic", ""),
            "last_message": last["last_message"],
            "last_message_time": last["last_message_time"],
            "last_message_sender_id": last["last_message_sender_id"],
            "msg_seen": seen_status
        })
    return jsonify({
        "contact_count": len(final_contacts),
        "contacts": final_contacts
    }), 200



#####  msg_seen_update ######

@app.route("/mark_msg_seen/<user_id>/<other_user>", methods=["PATCH"])
def mark_last_msg_seen(user_id, other_user):
    fetch_url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(and(sender_id.eq.{other_user},receiver_id.eq.{user_id}),"
        f"and(sender_id.eq.{user_id},receiver_id.eq.{other_user}))"
        f"&order=timestamp.desc"
        f"&limit=1"
    )
    last_msg_res = requests.get(fetch_url, headers=HEADERS)
    if last_msg_res.status_code != 200:
        return {"error": "failed to fetch last message"}, 400
    last_rows = last_msg_res.json()
    if not last_rows:
        return {"status": "no_messages"}, 200
    last_msg = last_rows[0]
    msg_id = last_msg["id"]
    sender = last_msg["sender_id"]
    receiver = last_msg["receiver_id"]
    if user_id != receiver:
        return {"status": "no_update_user_is_sender"}, 200
    update_url = f"{MESSAGES_REST_URL}?id=eq.{msg_id}"
    update_res = requests.patch(
        update_url,
        json={"msg_seen": "seen"},
        headers=HEADERS
    )
    if update_res.status_code in (200, 204):
        return {"status": "last_message_marked_seen"}, 200
    return {"error": "update_failed", "details": update_res.text}, 400





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
        json={"last_seen": datetime.now(ist).isoformat()},
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



###### delete user with messages ######

@app.route("/delete_user/<user_id>", methods=["DELETE"])
def delete_user_full(user_id):
    msg_url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(sender_id.eq.{user_id},receiver_id.eq.{user_id})"
    )
    msg_res = requests.delete(msg_url, headers=HEADERS)
    user_url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}"
    user_res = requests.delete(user_url, headers=HEADERS)

    if user_res.status_code == 204:
        return {
            "status": f"user '{user_id}' and related messages deleted"
        }, 200
    else:
        return {
            "error": "failed to delete user",
            "details": user_res.text
        }, 400
    


if __name__ == "__main__":
    app.run(debug=True)
