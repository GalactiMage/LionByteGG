"""
LionByteGG Web Dashboard Runner
Production-ready script for running the web dashboard.
Supports both development and production modes.
"""

import os
import sys
import socket
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

def get_local_ip():
    """Get the local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def run_development():
    """Run in development mode with Flask's built-in server"""
    local_ip = get_local_ip()
    print("=" * 60)
    print("LionByteGG Web Dashboard - DEVELOPMENT MODE")
    print("=" * 60)
    print(f"Local URL:   http://localhost:5000")
    print(f"LAN URL:     http://{local_ip}:5000")
    print("=" * 60)
    print("Share the LAN URL with others on your network!")
    print("Press CTRL+C to stop the server.")
    print("=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )

def run_production():
    """Run in production mode with Waitress (Windows-compatible)"""
    try:
        from waitress import serve
    except ImportError:
        print("ERROR: waitress is not installed. Run: pip install waitress")
        print("Falling back to Flask development server...")
        run_development()
        return
    
    local_ip = get_local_ip()
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print("LionByteGG Web Dashboard - PRODUCTION MODE")
    print("=" * 60)
    print(f"Server:      Waitress WSGI")
    print(f"Local URL:   http://localhost:{port}")
    print(f"LAN URL:     http://{local_ip}:{port}")
    print(f"Workers:     8 threads")
    print("=" * 60)
    print("Server is running. Press CTRL+C to stop.")
    print("=" * 60)
    
    serve(app, host='0.0.0.0', port=port, threads=8,
          channel_timeout=120, recv_bytes=65536)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='LionByteGG Web Dashboard')
    parser.add_argument('--production', '-p', action='store_true', 
                        help='Run in production mode with Waitress')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to run the server on (default: 5000)')
    args = parser.parse_args()
    
    if args.port != 5000:
        os.environ['PORT'] = str(args.port)
    
    if args.production or os.environ.get('FLASK_ENV') == 'production':
        run_production()
    else:
        run_development()
