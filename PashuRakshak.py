"""Offline PashuRakshak launcher and local API.

The reference HTML remains the product UI. This module provides a local-only
HTTP server so the same client can run on a laptop without internet access,
while keeping an SQLite record of submitted assessments.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
REFERENCE_HTML = ROOT / "COPILOT FOLDER" / "pashurakshak_ai_mobile_app.html"
DATABASE = ROOT / "pashurakshak_offline.db"
HOST = "127.0.0.1"
PORT = 8765

WEIGHTS = {
	"fever": 2,
	"mouth": 3,
	"lame": 2,
	"milk": 1,
	"nasal": 2,
	"cough": 1,
	"diar": 1,
	"nodules": 3,
	"death": 4,
	"abort": 2,
}


def initialize_database() -> None:
	with sqlite3.connect(DATABASE) as connection:
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS assessments (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
				payload TEXT NOT NULL,
				score INTEGER NOT NULL,
				level TEXT NOT NULL,
				disease TEXT NOT NULL
			)
			"""
		)


def assess_symptoms(data: dict) -> dict:
	symptoms = data.get("sy", [])
	score = sum(WEIGHTS.get(symptom, 1) for symptom in symptoms)
	score += int(data.get("dead", 0)) * 3
	if int(data.get("aff", 1)) > 3:
		score += 2
	if not data.get("vacc", False):
		score += 2

	symptom_set = set(symptoms)
	if "nodules" in symptom_set:
		disease = "lsd"
	elif {"mouth", "lame"}.issubset(symptom_set):
		disease = "fmd"
	elif {"death", "fever"}.issubset(symptom_set):
		disease = "ant"
	elif {"nasal", "cough"}.issubset(symptom_set):
		disease = "resp"
	elif "abort" in symptom_set:
		disease = "bru"
	else:
		disease = "unk"

	level = "high" if score >= 8 else "med" if score >= 5 else "low"
	return {**data, "score": score, "disease": disease, "level": level}


class PashuRakshakHandler(BaseHTTPRequestHandler):
	def _send_json(self, payload: dict, status: int = 200) -> None:
		body = json.dumps(payload).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self) -> None:  # noqa: N802
		path = urlparse(self.path).path
		if path == "/api/health":
			self._send_json({"ok": True, "offline": True})
			return
		if path == "/api/assessments":
			with sqlite3.connect(DATABASE) as connection:
				rows = connection.execute(
					"SELECT payload, score, level, disease, created_at "
					"FROM assessments ORDER BY id DESC"
				).fetchall()
			self._send_json(
				{
					"items": [
						{**json.loads(row[0]), "score": row[1], "level": row[2], "disease": row[3], "created_at": row[4]}
						for row in rows
					]
				}
			)
			return
		if path in {"/", "/index.html"}:
			if not REFERENCE_HTML.exists():
				self._send_json({"error": f"Missing reference UI: {REFERENCE_HTML}"}, 500)
				return
			body = REFERENCE_HTML.read_bytes()
			self.send_response(200)
			self.send_header("Content-Type", "text/html; charset=utf-8")
			self.send_header("Content-Length", str(len(body)))
			self.send_header("Cache-Control", "no-store")
			self.end_headers()
			self.wfile.write(body)
			return
		self._send_json({"error": "Not found"}, 404)

	def do_POST(self) -> None:  # noqa: N802
		if urlparse(self.path).path != "/api/assess":
			self._send_json({"error": "Not found"}, 404)
			return
		try:
			size = int(self.headers.get("Content-Length", "0"))
			data = json.loads(self.rfile.read(size))
			result = assess_symptoms(data)
		except (ValueError, json.JSONDecodeError, TypeError) as error:
			self._send_json({"error": str(error)}, 400)
			return

		with sqlite3.connect(DATABASE) as connection:
			connection.execute(
				"INSERT INTO assessments(payload, score, level, disease) VALUES (?, ?, ?, ?)",
				(json.dumps(data), result["score"], result["level"], result["disease"]),
			)
		self._send_json(result, 201)

	def log_message(self, format: str, *args: object) -> None:
		print(f"[PashuRakshak] {format % args}")


def run(open_browser: bool = True) -> None:
	initialize_database()
	server = ThreadingHTTPServer((HOST, PORT), PashuRakshakHandler)
	url = f"http://{HOST}:{PORT}/"
	print(f"PashuRakshak offline app: {url}")
	print(f"SQLite data: {DATABASE}")
	if open_browser:
		threading.Timer(0.4, lambda: webbrowser.open(url)).start()
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		print("\nStopping PashuRakshak.")
	finally:
		server.server_close()


if __name__ == "__main__":
	run()
