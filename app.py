
import os
import re
import secrets
from flask import Flask, request, jsonify, send_from_directory, Response
from upstash_redis import Redis

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:10000").rstrip("/")
DEV_NAME = os.environ.get("DEV_NAME", "Shiloh")
MAX_SITES = int(os.environ.get("MAX_SITES", "10"))

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,29}$")

RESERVED = {
    "admin", "api", "static", "login", "www",
    "health", "favicon", "index"
}


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "online"})


# CREATE / PUBLISH WEBSITE
@app.route("/api/sites", methods=["POST"])
def publish_site():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip().lower()
    html = data.get("html", "")

    if not NAME_RE.fullmatch(name):
        return jsonify({
            "error": "Invalid website name. Use 3-30 lowercase letters, numbers or hyphens."
        }), 400

    if name in RESERVED:
        return jsonify({"error": "This name is reserved."}), 400

    if not isinstance(html, str) or not html.strip():
        return jsonify({"error": "HTML content is required."}), 400

    if len(html.encode("utf-8")) > 2 * 1024 * 1024:
        return jsonify({"error": "Maximum HTML size is 2 MB."}), 413

    if redis.exists(f"site:{name}"):
        return jsonify({"error": "Website name already exists."}), 409

    # A private management key for the website owner
    owner_key = secrets.token_urlsafe(32)

    redis.set(f"site:{name}", html)
    redis.set(f"owner:{name}", owner_key)
    redis.sadd("all_sites", name)

    return jsonify({
        "success": True,
        "name": name,
        "url": f"{BASE_URL}/{name}",
        "owner_key": owner_key
    })


# UPDATE WEBSITE
@app.route("/api/sites/<name>", methods=["PUT"])
def update_site(name):
    name = name.lower()
    data = request.get_json(silent=True) or {}

    owner_key = data.get("owner_key", "")
    html = data.get("html", "")

    if not secrets.compare_digest(
        str(redis.get(f"owner:{name}") or ""),
        str(owner_key)
    ):
        return jsonify({"error": "Unauthorized."}), 403

    if not isinstance(html, str) or not html.strip():
        return jsonify({"error": "HTML content required."}), 400

    if len(html.encode("utf-8")) > 2 * 1024 * 1024:
        return jsonify({"error": "Maximum size is 2 MB."}), 413

    redis.set(f"site:{name}", html)

    return jsonify({
        "success": True,
        "message": "Website updated successfully."
    })


# DELETE WEBSITE
@app.route("/api/sites/<name>", methods=["DELETE"])
def delete_site(name):
    name = name.lower()
    data = request.get_json(silent=True) or {}
    owner_key = data.get("owner_key", "")

    if not secrets.compare_digest(
        str(redis.get(f"owner:{name}") or ""),
        str(owner_key)
    ):
        return jsonify({"error": "Unauthorized."}), 403

    redis.delete(f"site:{name}", f"owner:{name}")
    redis.srem("all_sites", name)

    return jsonify({"success": True})


# PUBLIC WEBSITE HOSTING
@app.route("/<name>")
def hosted_site(name):
    name = name.lower()

    content = redis.get(f"site:{name}")

    if not content:
        return Response(
            "<h1>404 - Website Not Found</h1>",
            status=404,
            mimetype="text/html"
        )

    return Response(
        str(content),
        mimetype="text/html"
    )


@app.errorhandler(413)
def file_too_large(error):
    return jsonify({"error": "Request too large. Maximum is 2 MB."}), 413


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
