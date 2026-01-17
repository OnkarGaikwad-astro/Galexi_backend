import json
import os
import requests
import base64   
from flask import Flask, request, jsonify
import pytz
from datetime import datetime
# import firebase_admin
from uuid import uuid4
# from firebase_admin import credentials, messaging
import base64
import requests
from flask import request, jsonify
from uuid import uuid4

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
    "Accept": "application/json",
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
    ensure_contact(sender, receiver)
    ensure_contact(receiver, sender)
    existing_shared_id = find_existing_chat(sender, receiver)
    if existing_shared_id:
        shared_id = existing_shared_id
    else:
        now = datetime.now(ist)
        shared_id = now.strftime("%Y%m%d%H%M%S")
    count_url = (
    f"{MESSAGES_REST_URL}"
    f"?id=eq.{shared_id}&conversation_id=gt.0&select=conversation_id"
)
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
    existing_chat = find_existing_chat(sender, receiver)
    if not existing_chat:
        base_row = {
            "id": shared_id,
            "conversation_id": 0,
            "sender_id": sender,
            "receiver_id": receiver,
            "msg": "",
            "timestamp": ""
        }
        requests.post(MESSAGES_REST_URL, json=base_row, headers=HEADERS)
    res = requests.post(MESSAGES_REST_URL, json=payload, headers=HEADERS)
    receiver_token = fetch_user_token(receiver)
    if receiver_token:
        sender_name = fetch_user_name(sender) or sender
        send_notification_to_server(
        receiver_token,
        title=sender_name,
        body= "⦿ Image" if '\uE000' in text else text
        )

    else:
        print("⚠️ No FCM token stored for this user:", receiver)
    return jsonify({
        "status": "message added",
        "shared_id": shared_id,
        "conversation_id": next_convo_id
    }), res.status_code


def fetch_user_name(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=name"
    res = requests.get(url, headers=HEADERS).json()
    if len(res) > 0:
        return res[0]["name"]
    return None
def fetch_user_token(user_id):
    url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=fcm_token"
    res = requests.get(url, headers=HEADERS).json()
    if len(res) > 0:
        return res[0]["fcm_token"]
    return None
def ensure_contact(user_id, contact_id):
    check_url = (
        f"{SUPABASE_URL}/rest/v1/user_contacts"
        f"?and=(user_id.eq.{user_id},contact_id.eq.{contact_id})"
    )
    exists = requests.get(check_url, headers=HEADERS).json()
    if exists:
        return  
    payload = {"user_id": user_id, "contact_id": contact_id}
    requests.post(
        f"{SUPABASE_URL}/rest/v1/user_contacts",
        json=payload,
        headers=HEADERS
    )



######  delete single message ######

@app.route("/delete_message/<user1>/<user2>/<convo_id>", methods=["DELETE"])
def delete_msg(user1, user2, convo_id):
    get_url = (
        f"{MESSAGES_REST_URL}"
        f"?or=("
        f"and(sender_id.eq.{user1},receiver_id.eq.{user2},conversation_id.eq.{convo_id}),"
        f"and(sender_id.eq.{user2},receiver_id.eq.{user1},conversation_id.eq.{convo_id})"
        f")"
        f"&select=pk,id"
        f"&limit=1"
    )
    msg = requests.get(get_url, headers=HEADERS).json()
    print("GET MESSAGE RESULT =", msg)
    if not msg:
        print("NO MESSAGE FOUND")
        return {"error": "message_not_found"}, 404
    shared_id = msg[0]["id"]
    print("STEP 1: shared_id =", shared_id)
    delete_url = f"{MESSAGES_REST_URL}?pk=eq.{msg[0]['pk']}"
    del_res = requests.delete(delete_url, headers=HEADERS)
    print("STEP 2: delete status =", del_res.status_code)
    fetch_url = (
        f"{MESSAGES_REST_URL}"
        f"?id=eq.{shared_id}&conversation_id=gt.0"
        f"&select=pk,conversation_id"
        f"&order=conversation_id.asc"
    )
    print("STEP 3: fetch_url =", fetch_url)
    msgs = requests.get(fetch_url, headers=HEADERS).json()
    print("STEP 4: msgs =", msgs)
    new_id = 1
    for m in msgs:
        print("PATCHING:", m)
        pk = m["pk"]
        patch_url = f"{MESSAGES_REST_URL}?pk=eq.{pk}"
        requests.patch(
            patch_url,
            json={"conversation_id": new_id},
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }
        )
        new_id += 1
    print("DONE RENUMBERING")
    return {"status": "done"}, 200



######  delete whole chat ######
@app.route("/clear_chat/<sender>/<receiver>", methods=["DELETE"])
def clear_chat(sender, receiver):
    url = (
        f"{MESSAGES_REST_URL}"
        f"?or=("
        f"and(sender_id.eq.{sender},receiver_id.eq.{receiver}),"
        f"and(sender_id.eq.{receiver},receiver_id.eq.{sender})"
        f")"
        f"&conversation_id=gt.0"
    )
    res = requests.delete(url, headers=HEADERS)
    if res.status_code == 204:
        return {"status": "chat cleared, contact retained"}, 200
    else:
        return {"error": "failed", "details": res.text}, 400



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
            "conversation_id":msg["conversation_id"],
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


##### search users ######
@app.route("/search_users/<query>", methods=["GET"])
def search_users(query):
    url = (
        f"{SUPABASE_URL}/rest/v1/users"
        f"?or=(user_id.ilike.%{query}%,name.ilike.%{query}%)"
        f"&select=user_id,name,profile_pic"
    )
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        return {"error": "failed", "details": res.text}, 400
    return {"count": len(res.json()), "users": res.json()}



##### get user contact list #####
@app.route("/user_contacts/<user_id>")
def user_contacts(user_id):

    manual_url = (
        f"{SUPABASE_URL}/rest/v1/user_contacts"
        f"?user_id=eq.{user_id}&select=contact_id"
    )
    manual_rows = requests.get(manual_url, headers=HEADERS).json()
    manual_set = {row["contact_id"] for row in manual_rows}
    chat_url = (
        f"{MESSAGES_REST_URL}"
        f"?or=(sender_id.eq.{user_id},receiver_id.eq.{user_id})"
        f"&select=sender_id,receiver_id,msg,msg_seen,timestamp"
        f"&order=timestamp.desc"
    )
    rows = requests.get(chat_url, headers=HEADERS).json()
    contact_map = {}
    for msg in rows:
        sender = msg["sender_id"]
        receiver = msg["receiver_id"]
        other = receiver if sender == user_id else sender
        if other not in contact_map:
            contact_map[other] = {
                "id": other,
                "last_message": msg["msg"],
                "last_message_time": msg["timestamp"],
                "last_message_sender_id": sender,
                "msg_seen": msg["msg_seen"] if user_id==receiver else "seen"
            }
    for contact_id in manual_set:
        if contact_id not in contact_map:
            contact_map[contact_id] = {
                "id": contact_id,
                "last_message": "",
                "last_message_time": "",
                "last_message_sender_id": "",
                "msg_seen": ""
            }
    if not contact_map:
        return {"contact_count": 0, "contacts": []}, 200
    ids_str = ",".join(contact_map.keys())
    users_url = (
        f"{SUPABASE_URL}/rest/v1/users"
        f"?user_id=in.({ids_str})"
        f"&select=user_id,name,profile_pic,bio"
    )
    user_rows = requests.get(users_url, headers=HEADERS).json()
    final_contacts = []
    for u in user_rows:
        uid = u["user_id"]
        info = contact_map[uid]
        final_contacts.append({
            "id": uid,
            "name": u.get("name", ""),
            "profile_pic": u.get("profile_pic", ""),
            "last_message": info["last_message"],
            "last_message_time": info["last_message_time"],
            "last_message_sender_id": info["last_message_sender_id"],
            "msg_seen": info["msg_seen"],
            "bio" : u.get("bio","")
        })
    return jsonify({
        "contact_count": len(final_contacts),
        "contacts": final_contacts
    }), 200





##### add contact to user contact list ######
@app.route("/add_contact", methods=["POST"])
def add_contact():
    body = request.json or {}
    user_id = body.get("user_id")
    contact_id = body.get("contact_id")
    if not user_id or not contact_id:
        return {"error": "user_id and contact_id required"}, 400
    check_url = (
        f"{SUPABASE_URL}/rest/v1/user_contacts"
        f"?and=(user_id.eq.{user_id},contact_id.eq.{contact_id})"
    )
    exists = requests.get(check_url, headers=HEADERS).json()
    if exists:
        return {"status": "already_exists"}, 200
    payload = {"user_id": user_id, "contact_id": contact_id}
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/user_contacts",
        json=payload,
        headers=HEADERS
    )
    if res.status_code in (200, 201):
        return {"status": "contact_added"}, 200
    return {"error": "insert_failed", "details": res.text}, 400


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
        json={"last_seen": datetime.now(ist).strftime("%Y-%m-%d \n %H:%M:%S")},
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

##### remove contact #####
@app.route("/remove_contact/<path:user1>/<path:user2>", methods=["DELETE"])
def remove_contact_and_clear_chat(user1, user2):
    user1 = user1.strip()
    user2 = user2.strip()

    # 1️⃣ Delete all messages between users (including base row)
    msg_delete_url = (
        f"{MESSAGES_REST_URL}"
        f"?or=("
        f"and(sender_id.eq.{user1},receiver_id.eq.{user2}),"
        f"and(sender_id.eq.{user2},receiver_id.eq.{user1})"
        f")"
    )
    requests.delete(msg_delete_url, headers=HEADERS)

    # 2️⃣ Delete contacts both ways
    contact_delete_url = (
        f"{SUPABASE_URL}/rest/v1/user_contacts"
        f"?or=("
        f"and(user_id.eq.{user1},contact_id.eq.{user2}),"
        f"and(user_id.eq.{user2},contact_id.eq.{user1})"
        f")"
    )
    requests.delete(contact_delete_url, headers=HEADERS)

    return {
        "status": "contact_removed_and_chat_cleared"
    }, 200

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
    
######  upload iamge ######

@app.route("/upload_image", methods=["POST"])
def upload_image():
    data = request.json
    if not data or "file" not in data:
        return jsonify({"error": "file missing"}), 400
    base64_file = data["file"].split(",")[-1]
    try:
        file_bytes = base64.b64decode(base64_file)
    except Exception:
        return jsonify({"error": "invalid base64"}), 400
    filename = f"{uuid4()}.jpg"
    upload_path = f"uploads/{filename}"
    upload_url = f"{SUPABASE_URL}/storage/v1/object/images/{upload_path}"
    res = requests.post(
        upload_url,
        headers={
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "apikey": SUPABASE_KEY,
            "Content-Type": "image/jpeg"
        },
        data=file_bytes
    )
    if res.status_code not in (200, 201):
        return jsonify({"error": res.text}), 500
    return jsonify({
        "status": "uploaded",
        "url": f"{SUPABASE_URL}/storage/v1/object/public/images/{upload_path}"
    }), 200


@app.route("/supabase")
def debug_supabase():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?limit=1",
        headers=HEADERS
    )
    return {
        "status_code": r.status_code,
        "text": r.text
    }


@app.errorhandler(Exception)
def handle_exception(e):
    return {
        "error": "internal_server_error",
        "message": str(e)
    }, 500



@app.route("/ping_db")
def ping_db():
    return {
        "SUPABASE_URL_PRESENT": bool(SUPABASE_URL),
        "SUPABASE_KEY_PRESENT": bool(SUPABASE_KEY)
    }

    

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

