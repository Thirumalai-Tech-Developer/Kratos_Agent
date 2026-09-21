"""
Elevated Helper Process.
Runs as High IL (Administrator) and listens on a named pipe for commands from Kratos.
Provides UAC-free input injection and file operations for the session.
"""
import sys
import os
import win32file
import win32pipe
import json
import logging
import time

logger = logging.getLogger(__name__)

def run_server(pipe_name: str, session_token: str):
    logger.info(f"Elevated helper started. Listening on {pipe_name}")
    
    # Create named pipe
    pipe = win32pipe.CreateNamedPipe(
        pipe_name,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        1, 65536, 65536,
        0,
        None
    )
    
    try:
        win32pipe.ConnectNamedPipe(pipe, None)
        logger.info("Client connected to elevated helper.")
        
        while True:
            # Read command from pipe
            hr, data = win32file.ReadFile(pipe, 65536)
            if not data:
                break
                
            payload = json.loads(data.decode("utf-8"))
            if payload.get("token") != session_token:
                logger.error("Invalid session token.")
                continue
                
            cmd = payload.get("command")
            args = payload.get("args", {})
            
            result = {"status": "ok", "message": "Command executed"}
            
            if cmd == "ping":
                result["message"] = "pong"
            elif cmd == "exit":
                break
            else:
                result = {"status": "error", "message": f"Unknown command: {cmd}"}
                
            # Send response
            win32file.WriteFile(pipe, json.dumps(result).encode("utf-8"))
            
    except Exception as e:
        logger.error(f"Elevated helper error: {e}")
    finally:
        win32file.CloseHandle(pipe)
        logger.info("Elevated helper shutting down.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
        
    pipe_name = sys.argv[1]
    session_token = sys.argv[2]
    
    run_server(pipe_name, session_token)
