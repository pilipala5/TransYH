"""Accept credentials on stdin, store in macOS Keychain, print only booleans."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from macos_keychain import put_api_key,get_api_key

try:
    cfg=json.loads(sys.stdin.readline())
    put_api_key(cfg['baseURL'],cfg['apiKey'])
    print(json.dumps({'stored':True,'readbackMatches':get_api_key(cfg['baseURL'])==cfg['apiKey']}))
except Exception:
    print(json.dumps({'stored':False,'message':'Could not store local Keychain credential'}))
    sys.exit(1)
