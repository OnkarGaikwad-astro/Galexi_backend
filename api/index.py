import os
import requests
from flask import Flask, request, jsonify
import datetime
import pytz
from datetime import datetime, timezone


app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True
ist = pytz.timezone("Asia/Kolkata")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

REST_URL = f"{SUPABASE_URL}/rest/v1/jsondb"

MESSAGES_REST_URL = f"{SUPABASE_URL}/rest/v1/messages"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}


@app.route("/")
def home():
    return {"Greet": "Hello Aurex"}



@app.route("/all")
def get_all():
    res = requests.get(REST_URL, headers=HEADERS)
    return jsonify(res.json()), res.status_code


@app.route("/get/<id>")
def get_by_id(id):
    url = f"{REST_URL}?id=eq.{id}"
    res = requests.get(url, headers=HEADERS)
    return jsonify(res.json()), res.status_code


@app.route("/update/<id>", methods=["PATCH", "POST"])
def update_row(id):
    res = requests.get(f"{REST_URL}?id=eq.{id}", headers=HEADERS)
    rows = res.json()
    old_data = rows[0]["data"]

    new_data = request.json
    updated_data = {**old_data, **new_data}

    patch_payload = {"data": updated_data}

    res2 = requests.patch(
        f"{REST_URL}?id=eq.{id}",
        json=patch_payload,
        headers=HEADERS
    )
    return jsonify(res2.json()), res2.status_code


@app.route("/delete/<id>", methods=["DELETE"])
def delete_row(id):
    res = requests.delete(f"{REST_URL}?id=eq.{id}", headers=HEADERS)
    return jsonify(res.json()), res.status_code


@app.route("/count")
def count_rows():
    res = requests.get(REST_URL, headers=HEADERS)
    return {"count": len(res.json())}

@app.route("/add_message", methods=["POST"])
def add_message():
    body = request.json or {}

    shared_id = body.get("id")     
    sender = body.get("sender_id")
    receiver = body.get("receiver_id")
    text = body.get("msg")

    if not shared_id or not sender or not receiver or not text:
        return {"error": "id, sender_id, msg required"}, 400

    count_url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&select=conversation_id"
    existing = requests.get(count_url, headers=HEADERS).json()

    next_convo_id = len(existing) + 1
    now = datetime.now(ist)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")

    payload = {
        "id": shared_id,                 
        "conversation_id": next_convo_id, 
        "sender_id": sender,
        "receiver_id": receiver,
        "msg": text,
        "timestamp": timestamp
    }

    res = requests.post(MESSAGES_REST_URL, json=payload, headers=HEADERS)
    return jsonify(res.json()), res.status_code

@app.route("/messages/<shared_id>")
def get_messages(shared_id):
    url = f"{MESSAGES_REST_URL}?id=eq.{shared_id}&order=timestamp.asc"
    res = requests.get(url, headers=HEADERS)
    return jsonify({"messages": res.json()}), res.status_code

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


@app.route("/conversations")
def conversations():
    url = f"{MESSAGES_REST_URL}?select=conversation_id"
    res = requests.get(url, headers=HEADERS)
    
    all_rows = res.json()
    seen = []

    for r in all_rows:
        cid = r.get("conversation_id")
        if cid not in seen:
            seen.append(cid)

    return jsonify({"conversations": seen}), 200

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    print("🔥 WEBHOOK TRIGGERED!")
    print("Method:", request.method)
    if request.method == "POST":
        print("POST DATA:", request.json)

    return {"Working": "Onkar"}, 200

if __name__ == "__main__":
    app.run(debug=True)
