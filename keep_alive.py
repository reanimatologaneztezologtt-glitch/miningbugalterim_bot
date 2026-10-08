"""
Replit ни ухлатмаслик учун mini web server
"""
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, *args):
        pass

def keep_alive():
    server = HTTPServer(("0.0.0.0", 8080), PingHandler)
    t = Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
